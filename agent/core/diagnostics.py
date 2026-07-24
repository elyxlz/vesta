"""SDK observability: activity tracking, stderr buffering, crash details, hang detection, context-usage logging."""

import asyncio
import collections
import time
import typing as tp

from claude_agent_sdk import ProcessError

from . import logger
from . import models as vm

_QUIET_NOTE_INTERVAL_S = 20.0  # one liveness note per interval of nothing-visible
_QUIET_ESCALATION_S = 300  # past this, dead air with no tool running is suspicious: warn + emit
_THINKING_TICK_FRESH_S = 30.0  # a thinking_tokens tick this recent proves the model is reasoning
_CONTEXT_USAGE_TIMEOUT_S = 10.0
_CONTEXT_USAGE_WARN_PCT = 80.0


def touch_activity(state: vm.State, label: str) -> None:
    state.last_sdk_activity = time.monotonic()
    state.last_sdk_activity_label = label


def sdk_idle_seconds(state: vm.State) -> float:
    return time.monotonic() - state.last_sdk_activity


def longest_running_tool(state: vm.State) -> vm.ActiveTool | None:
    if not state.active_tools:
        return None
    return min(state.active_tools.values(), key=lambda t: t.started_at)


def format_crash_detail(
    exc: BaseException, stderr_buffer: collections.deque[str], *, fallback: str = "(no stderr captured)"
) -> tuple[int | None, str]:
    """Extract exit_code and format stderr tail from an SDK exception."""
    exit_code = exc.exit_code if isinstance(exc, ProcessError) else None
    stderr_tail = "\n".join(stderr_buffer) if stderr_buffer else fallback
    return exit_code, stderr_tail


def format_hang_diagnostics(state: vm.State) -> str:
    parts = [f"idle={sdk_idle_seconds(state):.0f}s", f"last_activity={state.last_sdk_activity_label}"]
    longest = longest_running_tool(state)
    if longest:
        duration = time.monotonic() - longest.started_at
        parts.append(f"longest_tool={longest.name} ({duration:.0f}s, sub={longest.is_subagent})")
    if state.active_tools:
        parts.append(f"active_tools={len(state.active_tools)}")
    stderr_tail = list(state.stderr_buffer)[-5:] if state.stderr_buffer else []
    if stderr_tail:
        parts.append(f"stderr_tail={' | '.join(stderr_tail)}")
    return ", ".join(parts)


def make_stderr_handler(state: vm.State) -> tp.Callable[[str], None]:
    def handler(line: str) -> None:
        logger.sdk(line)
        state.stderr_buffer.append(line)

    return handler


def note_thinking_tick(turn: "vm.TurnSignals", *, tokens: int) -> None:
    """Record one thinking_tokens tick on the turn. The first tick of a turn logs "Thinking..."
    immediately (the wait loop only wakes once per poll interval); later ticks just refresh the
    counter and freshness timestamp that note_turn_liveness reads."""
    if turn.thinking_tokens_at is None:
        logger.client("Thinking...")
    turn.thinking_tokens = tokens
    turn.thinking_tokens_at = time.monotonic()


def note_turn_liveness(state: vm.State, *, turn: "vm.TurnSignals") -> None:
    """Log one liveness note per _QUIET_NOTE_INTERVAL_S while a turn produces nothing visible.

    Called from converse's wait loop — the one place that waits on the model, so this cannot
    silently stop running while turns still complete. The quiet clock is time since the last
    *visible* output (query sent, text or thinking emitted), because the stream itself is rarely
    silent: the CLI ticks a thinking_tokens counter throughout extended thinking (which is
    exactly why the old idle-based watchdog task never fired in production). Buckets are
    monotonic within a quiet stretch, so turn.quiet_noted_bucket rate-limits to one note per
    interval; both it and the once-per-stretch escalation flag reset when output lands.

    Specificity, best signal first: a tool in flight explains the quiet (its tool-call lines
    already show liveness) — debug. A recently ticking thinking counter means the model is
    demonstrably reasoning — calm INFO with the token count, never escalated. Otherwise the
    stream is genuinely dead air; the first note past _QUIET_ESCALATION_S is a warning + error
    event."""
    quiet = time.monotonic() - turn.last_visible_at
    bucket = int(quiet // _QUIET_NOTE_INTERVAL_S)
    if bucket < 1:
        turn.quiet_noted_bucket = 0
        turn.quiet_escalated = False
        return
    if bucket <= turn.quiet_noted_bucket:
        return
    turn.quiet_noted_bucket = bucket
    elapsed = int(bucket * _QUIET_NOTE_INTERVAL_S)
    thinking_live = turn.thinking_tokens_at is not None and (time.monotonic() - turn.thinking_tokens_at) < _THINKING_TICK_FRESH_S
    if state.active_tools:
        logger.debug(f"No output for {elapsed}s (tool in flight) | {format_hang_diagnostics(state)}")
    elif thinking_live:
        logger.client(f"Thinking for {elapsed}s (~{turn.thinking_tokens:,} tokens so far)")
    elif quiet >= _QUIET_ESCALATION_S and not turn.quiet_escalated:
        turn.quiet_escalated = True
        msg = f"No output and no stream activity for {elapsed}s | {format_hang_diagnostics(state)}"
        logger.warning(msg)
        # One event per quiet stretch, so a genuine stall reaches the observability surface
        # without spamming the stream.
        state.event_bus.emit({"type": "error", "text": msg})
    else:
        logger.client(f"Model quiet for {elapsed}s | {format_hang_diagnostics(state)}")


async def log_context_usage(state: vm.State) -> None:
    if not state.client:
        return
    try:
        usage = await asyncio.wait_for(state.client.get_context_usage(), timeout=_CONTEXT_USAGE_TIMEOUT_S)
        pct = usage["percentage"]
        total = usage["totalTokens"]
        max_tok = usage["maxTokens"]
        over_threshold = pct > _CONTEXT_USAGE_WARN_PCT
        log_fn = logger.warning if over_threshold else logger.usage
        summary = f"Context: {pct:.0f}% ({total:,}/{max_tok:,} tokens)"
        log_fn(summary)
        # Emit once on crossing into the warning band, not on every per-message check.
        if over_threshold and not state.context_warning_active:
            state.event_bus.emit({"type": "error", "text": f"Context usage above {_CONTEXT_USAGE_WARN_PCT:.0f}% | {summary}"})
        state.context_warning_active = over_threshold
    except TimeoutError:
        logger.warning(f"get_context_usage hung for {_CONTEXT_USAGE_TIMEOUT_S}s, skipping")
    except Exception as e:
        # Best-effort observability only. The official SDK's get_context_usage drives a control
        # request that can raise ClaudeSDKError or a bare Exception on an error/timeout response;
        # a context-usage probe must never escape and kill the message processor.
        logger.warning(f"context-usage probe failed: {e}")
