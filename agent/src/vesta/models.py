import asyncio
import collections
import dataclasses as dc
import datetime as dt

import pydantic as pyd
from claude_agent_sdk import ClaudeSDKClient

from .config import VestaConfig
from .events import EventBus

__all__ = ["State", "Notification", "VestaConfig"]

CLEAN_RESTART = "restart — clean restart"
NIGHTLY_RESTART = "nightly — dreamer ran, context compacted"
CRASH_RESTART = "crash — restarted after unexpected exit"


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
    stderr_buffer: collections.deque[str] = dc.field(default_factory=lambda: collections.deque(maxlen=50))
    api_failures: int = 0


class Notification(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="allow")

    timestamp: dt.datetime
    source: str
    type: str
    interrupt: bool = pyd.Field(default=True, exclude=True)
    file_path: str | None = pyd.Field(default=None, exclude=True)

    def format_for_display(self) -> str:
        data = self.model_dump(exclude={"file_path", "type", "source", "interrupt"})
        parts = [f"{k}={v}" for k, v in data.items() if v is not None]
        return f"[{self.type} from {self.source}] {', '.join(parts)}"
