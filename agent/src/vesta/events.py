"""Event bus for agent ↔ app communication over WebSocket."""

import asyncio
import collections
import datetime as dt
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


class ToolEndEvent(_BaseEvent):
    type: tp.Literal["tool_end"]
    tool: str


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


type StreamEvent = StatusEvent | ToolStartEvent | ToolEndEvent | AssistantEvent | UserEvent | ErrorEvent | NotificationEvent


class HistoryEvent(tp.TypedDict):
    type: tp.Literal["history"]
    events: list[StreamEvent]
    state: AgentState


type VestaEvent = StreamEvent | HistoryEvent

MAX_HISTORY = 5000


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[VestaEvent]] = set()
        self._state: AgentState = "idle"
        self.history: collections.deque[StreamEvent] = collections.deque(maxlen=MAX_HISTORY)

    def subscribe(self) -> asyncio.Queue[VestaEvent]:
        q: asyncio.Queue[VestaEvent] = asyncio.Queue(maxsize=MAX_HISTORY)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[VestaEvent]) -> None:
        self._subscribers.discard(q)

    def emit(self, event: StreamEvent) -> None:
        event["ts"] = dt.datetime.now().isoformat()
        if event["type"] != "status":
            self.history.append(event)
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
        self.history.clear()
