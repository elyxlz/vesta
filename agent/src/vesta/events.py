"""Event bus for agent event broadcasting and persistence."""

import asyncio
import datetime as dt
import json
import pathlib as pl
import sqlite3
import typing as tp

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


class ApiOutageEvent(_BaseEvent):
    type: tp.Literal["api_outage"]
    text: str
    retry_count: int


class ApiRecoveredEvent(_BaseEvent):
    type: tp.Literal["api_recovered"]


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
    | ApiOutageEvent
    | ApiRecoveredEvent
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


class EventBus:
    def __init__(self, data_dir: pl.Path | None = None) -> None:
        self._subscribers: set[asyncio.Queue[VestaEvent]] = set()
        self._state: AgentState = "idle"
        self._active_tools: int = 0
        self._conn: sqlite3.Connection | None = None
        if data_dir:
            data_dir.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(data_dir / "events.db"))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_EVENTS_SCHEMA)

    def subscribe(self) -> asyncio.Queue[VestaEvent]:
        q: asyncio.Queue[VestaEvent] = asyncio.Queue()
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
            q.put_nowait(event)

    @property
    def state(self) -> AgentState:
        return self._state

    def set_state(self, state: AgentState) -> None:
        if state == self._state:
            return
        self._state = state
        from vesta import logger

        logger.system(f"state → {state}")
        self.emit(StatusEvent(type="status", state=state))

    def tool_started(self) -> None:
        self._active_tools += 1

    def tool_finished(self) -> None:
        self._active_tools = max(0, self._active_tools - 1)

    def recent(self, limit: int = PAGE_SIZE) -> tuple[list[StreamEvent], int | None]:
        if not self._conn or limit <= 0:
            return [], None
        rows = self._conn.execute(
            "SELECT id, data FROM events ORDER BY id DESC LIMIT ?",
            (limit + 1,),
        ).fetchall()
        if not rows:
            return [], None
        has_older = len(rows) > limit
        rows = rows[:limit]
        events = [json.loads(r[1]) for r in reversed(rows)]
        return events, rows[-1][0] if has_older else None

    def before(self, cursor: int, limit: int = PAGE_SIZE) -> tuple[list[StreamEvent], int | None]:
        if not self._conn or limit <= 0:
            return [], None
        rows = self._conn.execute(
            "SELECT id, data FROM events WHERE id < ? ORDER BY id DESC LIMIT ?",
            (cursor, limit + 1),
        ).fetchall()
        if not rows:
            return [], None
        has_older = len(rows) > limit
        rows = rows[:limit]
        events = [json.loads(r[1]) for r in reversed(rows)]
        return events, rows[-1][0] if has_older else None

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
