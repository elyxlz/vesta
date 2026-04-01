import asyncio
import dataclasses as dc
import datetime as dt

import pydantic as pyd
from claude_agent_sdk import ClaudeSDKClient

from .config import VestaConfig
from .core.history import HistoryDB
from .events import EventBus

__all__ = ["State", "Notification", "VestaConfig"]


@dc.dataclass
class State:
    client: ClaudeSDKClient | None = None
    shutdown_event: asyncio.Event = dc.field(default_factory=asyncio.Event)
    graceful_shutdown: asyncio.Event = dc.field(default_factory=asyncio.Event)
    shutdown_count: int = 0
    session_id: str | None = None
    restart_reason: str | None = None
    last_dreamer_run: dt.datetime | None = None
    dreamer_active: bool = False
    interrupt_event: asyncio.Event | None = None
    event_bus: EventBus = dc.field(default_factory=EventBus)
    history: HistoryDB | None = None


class Notification(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="allow")

    timestamp: dt.datetime
    source: str
    type: str
    file_path: str | None = pyd.Field(default=None, exclude=True)

    def format_for_display(self) -> str:
        data = self.model_dump(exclude={"file_path", "type", "source"})
        parts = [f"{k}={v}" for k, v in data.items() if v is not None]
        return f"[{self.type} from {self.source}] {', '.join(parts)}"
