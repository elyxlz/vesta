"""SDK observability: activity tracking, stderr buffering, crash details, hang detection, context-usage logging."""

import asyncio
import collections
import time
import typing as tp

from . import logger
from . import models as vm

_SILENCE_THRESHOLDS_S = (60, 120, 300)
_SILENCE_ESCALATION_S = 300  # past this, quiet with no tool running is suspicious: warn + emit
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
    try:
        exit_code: int | None = exc.exit_code  # ty: ignore[unresolved-attribute]
    except AttributeError:
        exit_code = None
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


def note_stream_silence(state: vm.State, *, noted_at: set[int]) -> None:
    """Log bounded liveness lines while a turn waits out a quiet stream.

    Called from converse's wait loop — the one place that waits on the model, so this cannot
    silently stop running while turns still complete (unlike the background watchdog task it
    replaced, which never fired in production). One line per threshold crossing, cleared when
    the stream talks again, so a multi-minute extended-thinking stretch reads as "still
    thinking" instead of dead air, without flooding the log.

    A tool in flight explains the silence (a long build, a `sleep`, a subagent), so it logs at
    debug — the tool-call lines already show liveness. With no tool running, the early
    thresholds are calm INFO notes (long thinking is normal); past _SILENCE_ESCALATION_S the
    quiet is suspicious and escalates to a warning + error event, once."""
    idle = sdk_idle_seconds(state)
    if idle < _SILENCE_THRESHOLDS_S[0]:
        noted_at.clear()
        return
    for threshold in _SILENCE_THRESHOLDS_S:
        if idle < threshold or threshold in noted_at:
            continue
        noted_at.add(threshold)
        msg = f"Model quiet for {threshold}s (thinking or long generation) | {format_hang_diagnostics(state)}"
        if state.active_tools:
            logger.debug(msg)
        elif threshold >= _SILENCE_ESCALATION_S:
            logger.warning(msg)
            # One event per threshold crossing (noted_at gates re-emit), so a genuine stall
            # reaches the observability surface without spamming the stream.
            state.event_bus.emit({"type": "error", "text": msg})
        else:
            logger.client(msg)


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
