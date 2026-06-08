import asyncio
import collections
import dataclasses as dc
import datetime as dt
import time

import pydantic as pyd
from aiohttp.web import AppRunner
from core.cc_sdk import ClaudeSDKClient

from .config import VestaConfig, load_config
from .events import EventBus
from .provider import ProviderStatus
from .state_store import PersistedState

__all__ = ["State", "Notification", "VestaConfig", "PersistedState", "load_config"]

CORE_SOURCE = "core"

# Notification `type` values for `source=core` notifications. The filename stems
# match these prefixes so we can identify core notifications cheaply on disk.
TYPE_FIRST_START_SETUP = "first_start_setup"
TYPE_RESTART_GREETING = "restart_greeting"
TYPE_PROACTIVE_CHECK = "proactive_check"
TYPE_NIGHTLY_DREAM = "nightly_dream"
TYPE_MIGRATION = "migration"
TYPE_CONFIG_INVALID = "config_invalid"

CLEAN_RESTART = "restart: clean restart"
NIGHTLY_RESTART = "nightly: dreamer ran, session compacted for continuous context"
CRASH_RESTART = "crash: restarted after unexpected exit"
FIRST_START_REASON = "first start"


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
    shutdown_count: int = 0
    persisted: PersistedState = dc.field(default_factory=PersistedState)
    # Bound by run_vesta on every boot (mark_setup_done re-binds only as a fallback). The open WS port is the readiness signal vestad polls.
    ws_runner: AppRunner | None = None
    provider_status: ProviderStatus | None = None
    # Effective context window passed via CLAUDE_CODE_MAX_CONTEXT_TOKENS: the OpenRouter
    # model's real window (claude-code wrongly assumes 200k for non-Anthropic models,
    # claude-code#46416) capped at config.max_context_tokens to bound prompt-cache read
    # cost. Resolved once at boot. None = unresolved.
    openrouter_max_tokens: int | None = None
    # Local OpenRouter caching proxy: the SDK subprocess routes ANTHROPIC_BASE_URL here
    # so requests can be rewritten for prompt-cache hits. Both set once at boot.
    openrouter_proxy_url: str | None = None
    cache_proxy_runner: AppRunner | None = None
    interrupt_event: asyncio.Event | None = None
    compacting: bool = False
    # Set by mark_dreamer_complete; the message processor compacts the live session at the next
    # idle point, then triggers the restart (which resumes the compacted session). Deferred rather
    # than done inline because /compact only works while the session is idle, never mid-turn.
    compact_then_restart: bool = False
    processor_busy: bool = False
    event_bus: EventBus = dc.field(default_factory=EventBus)
    stderr_buffer: collections.deque[str] = dc.field(default_factory=lambda: collections.deque(maxlen=50))

    # SDK activity tracking for hang detection
    last_sdk_activity: float = dc.field(default_factory=time.monotonic)
    last_sdk_activity_label: str = "init"
    active_tools: dict[str, ActiveTool] = dc.field(default_factory=dict)
    # True while context usage is above the warning threshold, so log_context_usage emits
    # the warning event once on crossing rather than on every per-message check.
    context_warning_active: bool = False


class Notification(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="allow")

    timestamp: dt.datetime
    source: str
    type: str
    interrupt: bool = True
    body: str | None = None
    file_path: str | None = pyd.Field(default=None, exclude=True)

    def format_for_display(self) -> str:
        """Render the notification as an XML element for unambiguous parsing.

        When `body` is set it becomes the inner text (used by multi-line system prompts).
        Otherwise the remaining fields render as `key=value` attributes.

        Drops empty strings, False bools, empty lists, and None since they cost tokens without
        carrying information. Booleans should be named so True is the interesting case
        (`contact_unknown`, `is_forwarded`, `missed`). Strips microsecond precision from any
        datetime field.
        """
        if self.body is not None:
            return f'<notification source="{self.source}" type="{self.type}">\n{self.body.strip()}\n</notification>'
        data = self.model_dump(exclude={"file_path", "type", "source", "interrupt", "body"})
        parts = []
        for key, value in data.items():
            if value is None or value == "" or value is False or value == []:
                continue
            if isinstance(value, dt.datetime):
                value = value.replace(microsecond=0).isoformat()
            parts.append(f"{key}={value}")
        body = ", ".join(parts)
        return f'<notification source="{self.source}" type="{self.type}">{body}</notification>'
