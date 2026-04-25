import asyncio
import collections
import dataclasses as dc
import datetime as dt
import time

import pydantic as pyd
from claude_agent_sdk import ClaudeSDKClient

from .config import VestaConfig
from .events import EventBus

__all__ = ["State", "Notification", "VestaConfig"]

CLEAN_RESTART = "restart — clean restart"
NIGHTLY_RESTART = "nightly — dreamer ran, session cleared for fresh context"
CRASH_RESTART = "crash — restarted after unexpected exit"
PROCESSOR_CANCELLED_RESTART = "crash — processor cancelled unexpectedly"
PROCESSOR_SILENT_EXIT_RESTART = "crash — processor exited silently"
PROCESSING_CANCELLED_ERROR = "error — processing cancelled"


@dc.dataclass
class ActiveTool:
    name: str
    summary: str
    started_at: float
    is_subagent: bool = False


@dc.dataclass
class State:
    client: ClaudeSDKClient | None = None
    shutdown_event: asyncio.Event = dc.field(default_factory=asyncio.Event)
    graceful_shutdown: asyncio.Event = dc.field(default_factory=asyncio.Event)
    first_setup_complete: asyncio.Event = dc.field(default_factory=asyncio.Event)
    shutdown_count: int = 0
    session_id: str | None = None
    restart_reason: str | None = None
    last_dreamer_run: dt.datetime | None = None
    dreamer_active: bool = False
    interrupt_event: asyncio.Event | None = None
    event_bus: EventBus = dc.field(default_factory=EventBus)
    stderr_buffer: collections.deque[str] = dc.field(default_factory=lambda: collections.deque(maxlen=50))

    # SDK activity tracking for hang detection
    last_sdk_activity: float = dc.field(default_factory=time.monotonic)
    last_sdk_activity_label: str = "init"
    active_tools: dict[str, ActiveTool] = dc.field(default_factory=dict)

    def touch_activity(self, label: str) -> None:
        self.last_sdk_activity = time.monotonic()
        self.last_sdk_activity_label = label

    def sdk_idle_seconds(self) -> float:
        return time.monotonic() - self.last_sdk_activity

    def longest_running_tool(self) -> ActiveTool | None:
        if not self.active_tools:
            return None
        return min(self.active_tools.values(), key=lambda t: t.started_at)


class Notification(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="allow")

    timestamp: dt.datetime
    source: str
    type: str
    interrupt: bool = pyd.Field(default=True, exclude=True)
    file_path: str | None = pyd.Field(default=None, exclude=True)

    def format_for_display(self) -> str:
        """Render the notification as an XML element for unambiguous parsing.

        Drops empty strings, False bools, empty lists, and None since they cost tokens without
        carrying information. Booleans should be named so True is the interesting case
        (`contact_unknown`, `is_forwarded`, `missed`). Strips microsecond precision from any
        datetime field.
        """
        data = self.model_dump(exclude={"file_path", "type", "source", "interrupt"})
        parts = []
        for key, value in data.items():
            if value is None or value == "" or value is False or value == []:
                continue
            if isinstance(value, dt.datetime):
                value = value.replace(microsecond=0).isoformat()
            parts.append(f"{key}={value}")
        body = ", ".join(parts)
        return f'<notification source="{self.source}" type="{self.type}">{body}</notification>'
