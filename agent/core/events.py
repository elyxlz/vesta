"""Event bus for agent event broadcasting and persistence."""

import asyncio
import datetime as dt
import json
import logging
import pathlib as pl
import sqlite3
import typing as tp

logger = logging.getLogger("vesta.events")

EVENTS_DB_FILENAME = "events.db"

# Upper bound on events buffered per subscriber. A slow-but-alive WS client (phone
# on a weak link, wedged webview) whose send loop stalls would otherwise grow its
# queue without limit. 1000 events covers a long burst of streamed text/tool blocks
# while capping memory; a subscriber that overflows it is evicted (see _offer).
SUBSCRIBER_QUEUE_MAXSIZE = 1000

type AgentState = tp.Literal["idle", "thinking"]


class _BaseEvent(tp.TypedDict, total=False):
    ts: str


class StatusEvent(_BaseEvent):
    type: tp.Literal["status"]
    state: AgentState


class ToolStartEvent(_BaseEvent):
    type: tp.Literal["tool_start"]
    tool: str
    input: str
    subagent: bool


class ToolEndEvent(_BaseEvent):
    type: tp.Literal["tool_end"]
    tool: str
    subagent: bool


class AssistantEvent(_BaseEvent):
    type: tp.Literal["assistant"]
    text: str


class ThinkingEvent(_BaseEvent):
    type: tp.Literal["thinking"]
    text: str
    signature: str


class UserEvent(_BaseEvent):
    type: tp.Literal["user"]
    text: str
    input_method: tp.NotRequired[tp.Literal["voice", "typed"]]


class ErrorEvent(_BaseEvent):
    type: tp.Literal["error"]
    text: str


class RateLimitedEvent(_BaseEvent):
    type: tp.Literal["rate_limited"]
    text: str
    # The SDK's structured classification (see client._dispatch_message): the limit window that
    # tripped (five_hour, seven_day, ...) and the unix timestamp it resets at, when reported.
    window: str | None
    resets_at: int | None


class NotificationEvent(_BaseEvent):
    type: tp.Literal["notification"]
    source: str
    summary: str
    # Structured facets for the notifications history view + rule-editor suggestions. `sender` is ""
    # when the source attached no identity field. `decided` is what actually happened given the rules
    # at arrival. `notif_id` is the notification file's stem, used to tell whether it's still pending
    # (file on disk) or cleared. NotRequired because events predating the enrichment (and any
    # non-monitor emitter) lack them; readers already tolerate their absence. The production emit in
    # monitor_loop always supplies them.
    notif_type: tp.NotRequired[str]
    sender: tp.NotRequired[str]
    # The notification's targetable structured extras ({field: value}, e.g. {"chat_name": "Bride squad"}),
    # so the rule editor + the skill's `facets` can surface what an interrupt rule can match beyond
    # source/type/sender. NotRequired (events predating it, and notifications with no such extras, omit it).
    fields: tp.NotRequired[dict[str, str]]
    decided: tp.NotRequired[tp.Literal["interrupt", "snooze", "trash"]]
    notif_id: tp.NotRequired[str]


class NotificationClearedEvent(_BaseEvent):
    type: tp.Literal["notification_cleared"]
    # The cleared notification's file stem (matches a prior NotificationEvent.notif_id). Emitted when
    # the agent processes a notification and deletes its file. A live broadcast-only delta (never
    # persisted, see emit()): the notifications view seeds pending from the connect snapshot and then
    # removes ids as these arrive.
    notif_id: str


class SubagentStartEvent(_BaseEvent):
    type: tp.Literal["subagent_start"]
    agent_id: str
    agent_type: str


class SubagentStopEvent(_BaseEvent):
    type: tp.Literal["subagent_stop"]
    agent_id: str
    agent_type: str


class ChatEvent(_BaseEvent):
    type: tp.Literal["chat"]
    text: str


type StreamEvent = (
    StatusEvent
    | ToolStartEvent
    | ToolEndEvent
    | AssistantEvent
    | ThinkingEvent
    | UserEvent
    | ErrorEvent
    | RateLimitedEvent
    | NotificationEvent
    | NotificationClearedEvent
    | SubagentStartEvent
    | SubagentStopEvent
    | ChatEvent
)


# The connect handshake: one event sent directly to a client on a successful WS connect (not via
# the bus, so never persisted/broadcast). Each top-level key except `state` is a domain object so
# new connect-time state is added within a domain (or as a new domain) without disturbing readers;
# consumers read only the domains they care about (web: all; CLI: chat; vestad: state).
class SnapshotChat(tp.TypedDict):
    events: list[StreamEvent]  # recent app-chat seed; empty when the client connected with skip_history
    cursor: int | None  # load-older pagination cursor


class SnapshotNotifications(tp.TypedDict):
    pending: list[str]  # notification file stems still on disk (received but not yet processed)


class SnapshotEvent(tp.TypedDict):
    type: tp.Literal["snapshot"]
    state: AgentState
    chat: SnapshotChat
    notifications: SnapshotNotifications


# Bus-internal: the single item left in an evicted subscriber's queue (see EventBus._offer).
# The send loop closes the WS on it; never emitted, persisted, or sent to a client.
class EvictedEvent(_BaseEvent):
    type: tp.Literal["evicted"]


type VestaEvent = StreamEvent | SnapshotEvent | EvictedEvent

PAGE_SIZE = 50

# The conversation the chat surface shows by default: the user's messages and the agent's
# replies. The app-chat history window's cap and cursor count *these* (see _conversation_page),
# so notifications and other noise never push the conversation out of the capped window.
APP_CHAT_TYPES: tuple[str, ...] = ("user", "chat")

# Hidden-by-default events that ride along inside the window's id range (revealed by the
# chat's show-tools toggle) without counting toward the cap — so a burst of tool calls can't
# crowd the conversation out of the window, yet the toggle still has history to reveal.
APP_CHAT_OVERLAY_TYPES: tuple[str, ...] = ("tool_start",)


_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    data TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    text_content,
    content='events',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS events_fts_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, text_content)
    SELECT new.id, json_extract(new.data, '$.text')
    WHERE json_extract(new.data, '$.type') IN ('user', 'assistant', 'chat');
END;

CREATE TRIGGER IF NOT EXISTS events_fts_ad AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, text_content)
    SELECT 'delete', old.id, json_extract(old.data, '$.text')
    WHERE json_extract(old.data, '$.type') IN ('user', 'assistant', 'chat');
END;
"""

_RECENCY_DECAY_RATE = 0.01

# The notifications history channel: the arrivals list for the paginated view. Clears are not here —
# pending state is seeded from the connect snapshot and kept live via broadcast notification_cleared
# deltas, so the channel stays arrivals-only and pages aren't diluted by clear events.
_NOTIFICATION_CONDITION = "json_extract(data, '$.type') = 'notification'"

# Schema-version migration seam for events.db. `PRAGMA user_version` is the on-disk
# version; `_SCHEMA_VERSION` is the version this code expects. `_MIGRATIONS` is an
# ordered, version-gated list of (target_version, step) pairs applied in sequence at
# construction. Each step is idempotent: version 1 runs the baseline `_EVENTS_SCHEMA`
# (all `CREATE ... IF NOT EXISTS`), so a fresh db and a pre-versioned db with the
# tables already present both converge to version 1 with no data loss, the latter
# simply being stamped. Add future schema changes as version 2+ steps here; never
# edit a released step (existing dbs have already run it).
_SCHEMA_VERSION = 1


def _migrate_v1_baseline(conn: sqlite3.Connection) -> None:
    conn.executescript(_EVENTS_SCHEMA)


_MIGRATIONS: tuple[tuple[int, tp.Callable[[sqlite3.Connection], None]], ...] = ((1, _migrate_v1_baseline),)


def _migrate(conn: sqlite3.Connection) -> None:
    from . import logger

    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, step in _MIGRATIONS:
        if current >= version:
            continue
        step(conn)
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
        logger.startup(f"events.db migrated to schema version {version}")
        current = version


def _open(db_path: pl.Path) -> sqlite3.Connection:
    # timeout sets SQLite's busy handler: a write waits up to N seconds for a held lock (e.g. a
    # long-running VACUUM/maintenance op) instead of raising "database is locked" immediately.
    # Pairs with the guard in emit() below.
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    # Catches deep-page corruption (a hot-copied backup, bit rot) that a plain connect() would
    # let through lazily, so it surfaces here at boot rather than mid-turn during emit/recent.
    check = conn.execute("PRAGMA quick_check").fetchone()
    if check is None or check[0] != "ok":
        conn.close()
        raise sqlite3.DatabaseError(f"quick_check failed: {check}")
    _migrate(conn)
    return conn


def _quarantine(db_path: pl.Path) -> None:
    """Rename the corrupt db and its WAL/SHM siblings aside so a fresh one can take its place,
    preserving the original bytes for offline recovery instead of discarding history."""
    stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    for suffix in ("", "-wal", "-shm"):
        sibling = db_path.with_name(db_path.name + suffix)
        if sibling.exists():
            sibling.rename(db_path.with_name(f"{sibling.name}.corrupt-{stamp}"))


class EventBus:
    def __init__(self, data_dir: pl.Path | None = None) -> None:
        self._subscribers: set[asyncio.Queue[VestaEvent]] = set()
        self._state: AgentState = "idle"
        self._conn: sqlite3.Connection | None = None
        self._db_path: pl.Path | None = None
        if data_dir:
            from . import logger

            data_dir.mkdir(parents=True, exist_ok=True)
            self._db_path = data_dir / EVENTS_DB_FILENAME
            try:
                self._conn = _open(self._db_path)
            except sqlite3.DatabaseError as e:
                if isinstance(e, sqlite3.OperationalError):
                    # OperationalError is transient environment trouble (locked, disk full,
                    # IO error), not corruption: crash and let Docker's on-failure policy
                    # retry rather than quarantining a healthy db.
                    raise
                # A corrupt db must not crash-loop the container: quarantine it and boot with
                # empty history rather than burning Docker's on-failure restarts.
                logger.error(f"events.db corrupt ({e}), quarantining and starting fresh")
                _quarantine(self._db_path)
                self._conn = _open(self._db_path)

    def subscribe(self) -> asyncio.Queue[VestaEvent]:
        """A live event queue; yields a final EvictedEvent if the bus evicts it (see _offer)."""
        q: asyncio.Queue[VestaEvent] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAXSIZE)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[VestaEvent]) -> None:
        self._subscribers.discard(q)

    def emit(self, event: StreamEvent) -> None:
        event["ts"] = dt.datetime.now(dt.UTC).isoformat()
        # status (activity flips) and notification_cleared (pending deltas) are live-only signals with
        # no place in history — broadcast them but don't persist.
        if event["type"] not in ("status", "notification_cleared") and self._conn:
            # Event-logging is best-effort: a failed history write must NEVER crash the
            # agent loop. Without this guard, a transient "database is locked" (the db
            # held by a long maintenance op past the busy timeout) propagated out of emit
            # and took down the whole loop on every event, turning one stuck write into a
            # crash-restart storm. Drop the row with a warning and keep the agent alive.
            try:
                self._conn.execute(
                    "INSERT INTO events (ts, data) VALUES (?, ?)",
                    (event["ts"], json.dumps(event)),
                )
                self._conn.commit()
            except sqlite3.Error as e:
                logger.warning("event-log write failed, dropping event type=%s: %s", event["type"], e)
        for q in list(self._subscribers):
            self._offer(q, event)

    def _offer(self, q: asyncio.Queue[VestaEvent], event: StreamEvent) -> None:
        """Enqueue for one subscriber, evicting it on overflow.

        A subscriber either receives every event or gets a clean disconnect: one
        whose send loop stalls long enough to fall a full queue behind is getting
        no value from the live stream, so on overflow its stale backlog is replaced
        by a single EvictedEvent (with one warning, not one per event) telling its
        send loop to close the WS; the client reconnects and resyncs from the
        connect snapshot. History replay is delivered out-of-band on connect
        (api.py), never through this queue, so it is unaffected."""
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            self._subscribers.discard(q)
            # emit runs on the loop thread, so no other coroutine drains between
            # full here and the drain below: the queue stays at capacity.
            while not q.empty():
                q.get_nowait()
            q.put_nowait(EvictedEvent(type="evicted"))
            logger.warning(
                "subscriber stalled %d events behind, evicting so its client reconnects (latest type=%s)",
                SUBSCRIBER_QUEUE_MAXSIZE,
                event["type"],
            )

    @property
    def state(self) -> AgentState:
        return self._state

    def set_state(self, state: AgentState) -> None:
        if state == self._state:
            return
        self._state = state
        from . import logger

        logger.system(f"state → {state}")
        self.emit(StatusEvent(type="status", state=state))

    def _page(self, conditions: tuple[str, ...], params: tuple[object, ...], limit: int) -> tuple[list[StreamEvent], int | None]:
        if not self._db_path or limit <= 0:
            return [], None
        where = f"WHERE {' AND '.join(conditions)} " if conditions else ""
        # Open a short-lived read connection rather than reusing self._conn (bound to the
        # event loop thread): this lets callers run the query off the loop via
        # asyncio.to_thread, so a slow scan on a large db never freezes the agent. WAL lets
        # this reader run concurrently with the writer connection.
        conn = sqlite3.connect(str(self._db_path), timeout=30)
        try:
            rows = conn.execute(
                f"SELECT id, data FROM events {where}ORDER BY id DESC LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return [], None
        has_older = len(rows) > limit
        rows = rows[:limit]
        events = [json.loads(r[1]) for r in reversed(rows)]
        return events, rows[-1][0] if has_older else None

    def _conversation_page(self, limit: int, before_cursor: int | None) -> tuple[list[StreamEvent], int | None]:
        """The app-chat page: cap and cursor count conversation messages (APP_CHAT_TYPES),
        while tool-call overlay events (APP_CHAT_OVERLAY_TYPES) within the window's id range
        ride along — hidden until the show-tools toggle, but present so it has history to
        reveal — without ever spending the cap. Two steps: find the id of the oldest of the
        last `limit` conversation messages, then return everything visible from there up.
        Short-lived read connection so it can run off the event loop (see _page)."""
        if not self._db_path or limit <= 0:
            return [], None
        upper = "AND id < ? " if before_cursor is not None else ""
        upper_params: tuple[object, ...] = (before_cursor,) if before_cursor is not None else ()
        conv_ph = ",".join("?" for _ in APP_CHAT_TYPES)
        visible = (*APP_CHAT_TYPES, *APP_CHAT_OVERLAY_TYPES)
        vis_ph = ",".join("?" for _ in visible)
        conn = sqlite3.connect(str(self._db_path), timeout=30)
        try:
            conv_rows = conn.execute(
                f"SELECT id FROM events WHERE json_extract(data, '$.type') IN ({conv_ph}) {upper}ORDER BY id DESC LIMIT ?",
                (*APP_CHAT_TYPES, *upper_params, limit + 1),
            ).fetchall()
            if not conv_rows:
                return [], None
            has_older = len(conv_rows) > limit
            boundary = conv_rows[:limit][-1][0]
            rows = conn.execute(
                f"SELECT data FROM events WHERE json_extract(data, '$.type') IN ({vis_ph}) AND id >= ? {upper}ORDER BY id ASC",
                (*visible, boundary, *upper_params),
            ).fetchall()
        finally:
            conn.close()
        events = [json.loads(r[0]) for r in rows]
        return events, boundary if has_older else None

    def recent(self, limit: int = PAGE_SIZE, *, channel: str | None = None) -> tuple[list[StreamEvent], int | None]:
        if channel == "app-chat":
            return self._conversation_page(limit, None)
        if channel == "notifications":
            return self._page((_NOTIFICATION_CONDITION,), (), limit)
        return self._page((), (), limit)

    def before(self, cursor: int, limit: int = PAGE_SIZE, *, channel: str | None = None) -> tuple[list[StreamEvent], int | None]:
        if channel == "app-chat":
            return self._conversation_page(limit, cursor)
        if channel == "notifications":
            return self._page((_NOTIFICATION_CONDITION, "id < ?"), (cursor,), limit)
        return self._page(("id < ?",), (cursor,), limit)

    def search(self, query: str, *, limit: int = 20) -> list[StreamEvent]:
        """Full-text search over events, returning the matching events in the same shape as recent()
        (so /history can serve both recency and search), ranked by FTS relevance decayed toward recent.
        Short-lived read connection so it can run off the event loop (see _page): an FTS MATCH over a
        years-old db must never freeze the agent, and never interleave with emit's writer-connection
        transactions."""
        if not self._db_path:
            return []
        conn = sqlite3.connect(str(self._db_path), timeout=30)
        try:
            rows = conn.execute(
                """
                SELECT e.data,
                       f.rank / (1.0 + ? * max(julianday('now') - julianday(e.ts), 0)) AS score
                FROM events_fts f
                JOIN events e ON e.id = f.rowid
                WHERE events_fts MATCH ?
                ORDER BY score ASC
                LIMIT ?
                """,
                (_RECENCY_DECAY_RATE, query, limit),
            ).fetchall()
        finally:
            conn.close()
        return [json.loads(r[0]) for r in rows]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
