"""Event bus for agent ↔ app communication over WebSocket."""

import asyncio
import datetime as dt
import json
import pathlib as pl
import sqlite3
import typing as tp

type AgentState = tp.Literal["idle", "thinking", "tool_use"]


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


type StreamEvent = (
    StatusEvent
    | ToolStartEvent
    | ToolEndEvent
    | AssistantEvent
    | UserEvent
    | ErrorEvent
    | NotificationEvent
    | SubagentStartEvent
    | SubagentStopEvent
    | ChatEvent
)

CHAT_TYPES: frozenset[str] = frozenset({"user", "chat", "tool_start", "tool_end", "status", "error"})
INTERNALS_TYPES: frozenset[str] = frozenset(
    {"user", "assistant", "tool_start", "tool_end", "status", "error", "notification", "subagent_start", "subagent_stop"}
)


class HistoryEvent(tp.TypedDict):
    type: tp.Literal["history"]
    events: list[StreamEvent]
    state: AgentState
    cursor: int | None


type VestaEvent = StreamEvent | HistoryEvent

PAGE_SIZE = 100
MAX_SUBSCRIBER_QUEUE = 5000

_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    ts TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_channel_id ON events (channel, id);
"""


class _HistoryLog:
    """SQLite-backed event log for a specific channel."""

    def __init__(self, conn: sqlite3.Connection, channel: str, types: frozenset[str]) -> None:
        self._conn = conn
        self._channel = channel
        self.types = types

    def append(self, event: StreamEvent) -> None:
        if event["type"] in self.types:
            self._conn.execute(
                "INSERT INTO events (channel, ts, data) VALUES (?, ?, ?)",
                (self._channel, event.get("ts", ""), json.dumps(event)),
            )
            self._conn.commit()

    def recent(self, limit: int = PAGE_SIZE) -> tuple[list[StreamEvent], int | None]:
        rows = self._conn.execute(
            "SELECT id, data FROM events WHERE channel = ? ORDER BY id DESC LIMIT ?",
            (self._channel, limit),
        ).fetchall()
        if not rows:
            return [], None
        events = [json.loads(r[1]) for r in reversed(rows)]
        oldest_id = rows[-1][0]
        has_older = (
            self._conn.execute(
                "SELECT 1 FROM events WHERE channel = ? AND id < ? LIMIT 1",
                (self._channel, oldest_id),
            ).fetchone()
            is not None
        )
        return events, oldest_id if has_older else None

    def before(self, cursor: int, limit: int = PAGE_SIZE) -> tuple[list[StreamEvent], int | None]:
        rows = self._conn.execute(
            "SELECT id, data FROM events WHERE channel = ? AND id < ? ORDER BY id DESC LIMIT ?",
            (self._channel, cursor, limit),
        ).fetchall()
        if not rows:
            return [], None
        events = [json.loads(r[1]) for r in reversed(rows)]
        oldest_id = rows[-1][0]
        has_older = (
            self._conn.execute(
                "SELECT 1 FROM events WHERE channel = ? AND id < ? LIMIT 1",
                (self._channel, oldest_id),
            ).fetchone()
            is not None
        )
        return events, oldest_id if has_older else None

    def clear(self) -> None:
        self._conn.execute("DELETE FROM events WHERE channel = ?", (self._channel,))
        self._conn.commit()


class EventBus:
    def __init__(self, data_dir: pl.Path | None = None) -> None:
        self._subscribers: set[asyncio.Queue[VestaEvent]] = set()
        self._state: AgentState = "idle"
        self._conn: sqlite3.Connection | None = None
        self._logs: dict[str, _HistoryLog] = {}
        if data_dir:
            data_dir.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(data_dir / "events.db"))
            self._conn.executescript(_EVENTS_SCHEMA)
            self._logs["chat"] = _HistoryLog(self._conn, "chat", CHAT_TYPES)
            self._logs["internals"] = _HistoryLog(self._conn, "internals", INTERNALS_TYPES)

    def log(self, channel: str) -> _HistoryLog | None:
        return self._logs.get(channel)

    def subscribe(self) -> asyncio.Queue[VestaEvent]:
        q: asyncio.Queue[VestaEvent] = asyncio.Queue(maxsize=MAX_SUBSCRIBER_QUEUE)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[VestaEvent]) -> None:
        self._subscribers.discard(q)

    def emit(self, event: StreamEvent) -> None:
        event["ts"] = dt.datetime.now(dt.UTC).isoformat()
        if event["type"] != "status":
            for history_log in self._logs.values():
                history_log.append(event)
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    @property
    def state(self) -> AgentState:
        return self._state

    def set_state(self, state: AgentState) -> None:
        if state == self._state:
            return
        self._state = state
        self.emit(StatusEvent(type="status", state=state))

    def clear_history(self) -> None:
        for history_log in self._logs.values():
            history_log.clear()

    def close(self) -> None:
        self._logs.clear()
        if self._conn:
            self._conn.close()
            self._conn = None
