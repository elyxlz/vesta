import asyncio
import collections
import dataclasses as dc
import datetime as dt
import time
import typing as tp

import pydantic as pyd
from aiohttp.web import AppRunner
from claude_agent_sdk import ClaudeSDKClient

from .config import ClaudeConfig, OpenRouterConfig, Provider, VestaConfig, load_config, migrate_legacy_config_to_store
from .events import EventBus
from .notification_interrupt_policy import CORE_SOURCE
from .provider import ProviderStatus
from .state_store import PersistedState

__all__ = [
    "State",
    "Notification",
    "VestaConfig",
    "ClaudeConfig",
    "OpenRouterConfig",
    "Provider",
    "PersistedState",
    "CORE_SOURCE",
    "load_config",
    "migrate_legacy_config_to_store",
]

# Notification `type` values for the `source=core` notifications that remain notifications (periodic
# control-flow). Boot-time control-flow (greeting, migrations, skill-sync, config issues) is delivered
# as boot turns instead — see core/main.py collect_boot_turns — so it carries no notification type.
TYPE_PROACTIVE_CHECK = "proactive_check"
TYPE_NIGHTLY_DREAM = "nightly_dream"

# Core notifications are exempt from the user's rules; loops.py derives their disposition from the type.
# Types listed here pool (wait for idle); every other core type interrupts.
CORE_POOL_TYPES = frozenset({TYPE_PROACTIVE_CHECK})


class QueuedTurn(tp.NamedTuple):
    """One item in the agent's processing queue: a prompt plus how to handle it.

    `interruptible=False` marks a boot turn — boot-time control-flow that must run to completion;
    a later-queued message waits its turn instead of preempting it."""

    text: str
    is_user: bool
    file_paths: list[str]
    interruptible: bool = True


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
class TurnSignals:
    """Bridge between the long-lived stream consumer (writer) and the turn driver (waiter).

    The consumer accumulates the open turn's text and closes `done` when the turn's
    ResultMessage arrives (or the stream dies, carried in `error`). Attribution is advisory:
    the stream-json protocol has no query<->result correlation, so a ResultMessage closes
    whichever turn is open and one arriving with no open turn is dropped."""

    show_output: bool = True
    texts: list[str] = dc.field(default_factory=list)
    done: asyncio.Event = dc.field(default_factory=asyncio.Event)
    error: Exception | None = None
    last_message_at: float = dc.field(default_factory=time.monotonic)
    # Liveness for the turn's wait loop (owned by diagnostics.note_turn_liveness /
    # note_thinking_tick): the CLI streams a thinking_tokens counter while the model reasons
    # (tracked here, never logged per-delta), last_visible_at marks the last output the user
    # could see (query sent, text, or thinking emitted), and the quiet_* pair rate-limits the
    # notes to one per interval with a single escalation per quiet stretch.
    thinking_tokens: int = 0
    thinking_tokens_at: float | None = None
    last_visible_at: float = dc.field(default_factory=time.monotonic)
    quiet_noted_bucket: int = 0
    quiet_escalated: bool = False


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
    # claude-code#46416) capped at config.provider.max_context_tokens to bound prompt-cache read
    # cost. Resolved once at boot. None = unresolved.
    openrouter_max_tokens: int | None = None
    # Local OpenRouter caching proxy: the SDK subprocess routes ANTHROPIC_BASE_URL here
    # so requests can be rewritten for prompt-cache hits. Both set once at boot.
    openrouter_proxy_url: str | None = None
    cache_proxy_runner: AppRunner | None = None
    interrupt_event: asyncio.Event | None = None
    # The currently open turn's signals; written by the stream consumer, waited on by converse /
    # compact_session. None while no turn is open (results arriving then are dropped as advisory).
    turn: TurnSignals | None = None
    compacting: bool = False
    # True while a non-interruptible turn (a boot turn) is being processed. process_batch consults
    # this before firing client.interrupt(), so a concurrent interrupt notification queues and waits
    # rather than SDK-aborting the boot turn mid-stream (the queue-watcher's interruptible guard only
    # covers the queue-driven path, not this direct SDK path).
    noninterruptible_turn_active: bool = False
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
    # The producing skill's default disposition, used when no user rule matches (True -> interrupt,
    # False -> pool). See notification_interrupt_policy.should_interrupt.
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
        data = self.model_dump(exclude={"file_path", "type", "source", "body", "interrupt"})
        parts = []
        for key, value in data.items():
            if value is None or value == "" or value is False or value == []:
                continue
            if isinstance(value, dt.datetime):
                value = value.replace(microsecond=0).isoformat()
            parts.append(f"{key}={value}")
        body = ", ".join(parts)
        return f'<notification source="{self.source}" type="{self.type}">{body}</notification>'
