import asyncio
import dataclasses as dc
import datetime as dt

import pydantic as pyd
from claude_agent_sdk import ClaudeSDKClient

from .config import VestaConfig

__all__ = ["State", "Notification", "VestaConfig"]


@dc.dataclass
class State:
    client: ClaudeSDKClient | None = None
    shutdown_event: asyncio.Event | None = None
    shutdown_count: int = 0
    is_processing: bool = False
    reset_requested: bool = False
    sub_agent_context: str | None = None
    session_id: str | None = None
    pending_error_context: str | None = None
    last_memory_consolidation: dt.datetime | None = None
    processing_lock: asyncio.Lock = dc.field(default_factory=asyncio.Lock)


class Notification(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="allow")

    timestamp: dt.datetime
    source: str
    type: str
    file_path: str | None = pyd.Field(default=None, exclude=True)

    def format_for_display(self) -> str:
        data = self.model_dump(exclude={"file_path"})
        parts = [f"{k}={v}" for k, v in data.items() if v is not None]
        return f"[{self.type} from {self.source}] {', '.join(parts)}"
