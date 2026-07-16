import asyncio
import collections
import dataclasses as dc
import time
import typing as tp

from aiohttp.web import AppRunner
from claude_agent_sdk import ClaudeSDKClient

from .events import EventBus
from .provider import ProviderStatus
from .state_store import PersistedState


class QueuedTurn(tp.NamedTuple):
    """One item in the agent's processing queue: a prompt plus how to handle it.

    `interruptible=False` marks a boot turn: boot-time control-flow that must run to completion;
    a later-queued message waits its turn instead of preempting it."""

    text: str
    is_user: bool
    file_paths: list[str]
    interruptible: bool = True


CLEAN_RESTART = "clean: routine restart, no specific reason"
CRASH_RESTART = "crash: restarted after an unexpected exit"
FIRST_START_REASON = "first start"


def is_crash_reason(reason: str | None) -> bool:
    """Whether a restart reason marks an unexpected exit (the `crash:`/`error:` categories the
    processor/loop error handlers write). The single owner of the crash-category vocabulary: it
    drives the non-zero exit that lets Docker's on-failure policy recover the agent, the
    inbox-override precedence on boot, and the render (crash reasons keep their marker)."""
    return reason is not None and (reason.startswith(("crash:", "error:")))


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
    # Set by send_preempt when a priority:"now" prompt is delivered while this turn runs: the
    # reply is being cut short at the CLI's next step boundary, so followups that assume a
    # complete reply (the dash-correction turn) are skipped.
    preempted: bool = False
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


@dc.dataclass(frozen=True)
class PendingCompaction:
    """A deferred /compact scheduled between turns (compact_session only runs on an idle
    session). prompt guides the summarizer; followup is an optional turn delivered after
    compacting; restart means restart into the compacted session afterward. The drain routes
    the followup to a restart-safe channel."""

    prompt: str | None
    followup: str | None
    restart: bool


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
    # The currently open turn's signals; written by the stream consumer, waited on by converse /
    # compact_session. None while no turn is open (results arriving then are dropped as advisory).
    turn: TurnSignals | None = None
    compacting: bool = False
    # True while a non-interruptible turn (a boot turn) is being processed. send_preempt consults
    # this, so a concurrent interrupting notification queues and waits rather than preempting the
    # boot turn mid-stream.
    noninterruptible_turn_active: bool = False
    # File paths of the notification the current turn is handling (empty for user-message turns).
    # The message loop clears these after the turn; the restart/stop tools clear them first when an
    # intentional restart fires mid-turn, since the notification is already handled and its file
    # would otherwise survive the SIGTERM and be re-delivered on reboot.
    in_flight_notification_paths: list[str] = dc.field(default_factory=list)
    # Set by run_one when the current turn's query never reached the CLI (QueryNotDeliveredError): the
    # message loop then keeps in_flight_notification_paths instead of clearing it, since the
    # resumed session never saw the message. Reset at the start of every turn.
    query_not_delivered: bool = False
    # A deferred compaction scheduled by the compact_context tool, drained after the turn's
    # batch (since /compact needs an idle session). In-memory only: a mid-turn crash drops it.
    pending_compaction: PendingCompaction | None = None
    # The last rejected rate-limit window surfaced as an error event, as (rate_limit_type,
    # resets_at): the CLI re-reports the same rejection on every retry, so _dispatch_message
    # announces each window once (issue #1071).
    rate_limit_noticed: tuple[str | None, int | None] | None = None
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
