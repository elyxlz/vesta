"""Event bus for agent event broadcasting and persistence."""

import asyncio
import datetime as dt
import json
import logging
import pathlib as pl
import sqlite3
import typing as tp

logger = logging.getLogger("vesta.events")

# Upper bound on events buffered per subscriber. A slow-but-alive WS client (phone
# on a weak link, wedged webview) whose send loop stalls would otherwise grow its
# queue without limit. 1000 events covers a long burst of streamed text/tool blocks
# while capping memory; on overflow we drop the oldest event (see emit) so the
# stream stays current rather than replaying a stale backlog.
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


class NotificationEvent(_BaseEvent):
    type: tp.Literal["notification"]
    source: str
    summary: str


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
    | NotificationEvent
    | SubagentStartEvent
    | SubagentStopEvent
    | ChatEvent
)


class HistoryEvent(tp.TypedDict):
    type: tp.Literal["history"]
    events: list[StreamEvent]
    state: AgentState
    cursor: int | None


type VestaEvent = StreamEvent | HistoryEvent

PAGE_SIZE = 100

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


class EventBus:
    def __init__(self, data_dir: pl.Path | None = None) -> None:
        self._subscribers: set[asyncio.Queue[VestaEvent]] = set()
        self._state: AgentState = "idle"
        self._conn: sqlite3.Connection | None = None
        if data_dir:
            data_dir.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(data_dir / "events.db"))
            self._conn.execute("PRAGMA journal_mode=WAL")
            _migrate(self._conn)

    def subscribe(self) -> asyncio.Queue[VestaEvent]:
        q: asyncio.Queue[VestaEvent] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAXSIZE)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[VestaEvent]) -> None:
        self._subscribers.discard(q)

    def emit(self, event: StreamEvent) -> None:
        event["ts"] = dt.datetime.now(dt.UTC).isoformat()
        if event["type"] != "status" and self._conn:
            self._conn.execute(
                "INSERT INTO events (ts, data) VALUES (?, ?)",
                (event["ts"], json.dumps(event)),
            )
            self._conn.commit()
        for q in self._subscribers:
            self._offer(q, event)

    def _offer(self, q: asyncio.Queue[VestaEvent], event: StreamEvent) -> None:
        """Enqueue for one subscriber, dropping its oldest event on overflow.

        A stalled send loop must not pin memory: when the queue is full we evict
        the oldest buffered event to make room for the newest, keeping the live
        stream current. History replay is delivered out-of-band on connect (api.py),
        never through this queue, so it is unaffected."""
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # emit runs on the loop thread, so no other coroutine drains between
            # full and get_nowait: the queue is non-empty here by construction.
            dropped = q.get_nowait()
            logger.warning("subscriber queue full, dropped oldest event type=%s", dropped["type"])
            q.put_nowait(event)

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

    def _page(self, where_clause: str, params: tuple[object, ...], limit: int) -> tuple[list[StreamEvent], int | None]:
        if not self._conn or limit <= 0:
            return [], None
        rows = self._conn.execute(
            f"SELECT id, data FROM events {where_clause}ORDER BY id DESC LIMIT ?",
            (*params, limit + 1),
        ).fetchall()
        if not rows:
            return [], None
        has_older = len(rows) > limit
        rows = rows[:limit]
        events = [json.loads(r[1]) for r in reversed(rows)]
        return events, rows[-1][0] if has_older else None

    def recent(self, limit: int = PAGE_SIZE) -> tuple[list[StreamEvent], int | None]:
        return self._page("", (), limit)

    def before(self, cursor: int, limit: int = PAGE_SIZE) -> tuple[list[StreamEvent], int | None]:
        return self._page("WHERE id < ? ", (cursor,), limit)

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, str]]:
        if not self._conn:
            return []
        rows = self._conn.execute(
            """
            SELECT e.ts, json_extract(e.data, '$.type') AS role, json_extract(e.data, '$.text') AS content,
                   f.rank / (1.0 + ? * max(julianday('now') - julianday(e.ts), 0)) AS score
            FROM events_fts f
            JOIN events e ON e.id = f.rowid
            WHERE events_fts MATCH ?
            ORDER BY score ASC
            LIMIT ?
            """,
            (_RECENCY_DECAY_RATE, query, limit),
        ).fetchall()
        return [{"timestamp": r[0], "role": r[1], "content": r[2]} for r in rows]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
