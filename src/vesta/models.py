"""Vesta domain models - depends on config layer."""

import asyncio
import dataclasses as dc
import datetime as dt
import typing as tp

import pydantic as pyd
from claude_agent_sdk import ClaudeSDKClient

# Re-export from config for backward compatibility
from .config import VestaSettings

__all__ = ["State", "Notification", "VestaSettings", "ConversationMessage"]


class ConversationMessage(tp.TypedDict):
    role: str
    content: str


@dc.dataclass
class State:
    client: ClaudeSDKClient | None = None
    shutdown_event: asyncio.Event | None = None
    shutdown_count: int = 0
    is_processing: bool = False
    sub_agent_context: str | None = None
    session_id: str | None = None
    pending_system_message: str | None = None
    last_memory_consolidation: dt.datetime | None = None
    processing_lock: asyncio.Lock = dc.field(default_factory=asyncio.Lock)
    conversation_history: list[ConversationMessage] = dc.field(default_factory=list)
    conversation_history_lock: asyncio.Lock = dc.field(default_factory=asyncio.Lock)
    subagent_conversations: dict[str, list[str]] = dc.field(default_factory=dict)
    subagent_conversations_lock: asyncio.Lock = dc.field(default_factory=asyncio.Lock)


class Notification(pyd.BaseModel):
    timestamp: dt.datetime
    source: str
    type: str
    message: str
    sender: str | None = None
    metadata: dict[str, tp.Any] = pyd.Field(default_factory=dict)
    file_path: str | None = pyd.Field(default=None, exclude=True)

    def format_for_display(self) -> str:
        meta_str = ""
        if self.metadata:
            meta_items = [f"{k}={v}" for k, v in self.metadata.items() if v]
            meta_str = f" (metadata: {', '.join(meta_items)})" if meta_items else ""

        from_str = self.sender if self.sender else self.source
        return f"[{self.type} from {from_str}]{meta_str}: {self.message}"
