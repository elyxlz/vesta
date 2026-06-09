"""SDK observability: activity tracking, stderr buffering, crash details, hang detection, context-usage logging."""

import asyncio
import collections
import re
import time
import typing as tp

from . import logger
from . import models as vm

_WATCHDOG_THRESHOLDS_S = (60, 120, 300)
_CONTEXT_USAGE_TIMEOUT_S = 10.0
_CONTEXT_USAGE_WARN_PCT = 80.0
_PANE_CAPTURE_TIMEOUT_S = 5.0
_PANE_TAIL_LINES = 4
_PANE_TAIL_MAXLEN = 240
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def format_pane_tail(pane: str) -> str:
    """Condense a raw TUI capture to its last few content lines, ANSI-stripped.

    Keeps the watchdog warning a single readable line: blank lines and pure box-drawing
    rules are dropped, only the tail (where the prompt and any error live) is kept, and the
    result is length-capped so a wedged-pane dump never floods the log stream.
    """
    lines = []
    for raw in pane.splitlines():
        stripped = _ANSI_RE.sub("", raw).strip()
        if any(ch.isalnum() for ch in stripped):
            lines.append(stripped)
    return " | ".join(lines[-_PANE_TAIL_LINES:])[:_PANE_TAIL_MAXLEN]


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


def _check_sdk_subprocess_alive(state: vm.State) -> bool | None:
    """Returns None if we can't determine (no client, or session not yet launched)."""
    if state.client is None:
        return None
    return state.client.is_alive()


async def _capture_pane_tail(state: vm.State) -> str:
    """Best-effort, bounded snapshot of the claude TUI tail; empty string if unavailable."""
    if state.client is None:
        return ""
    try:
        pane = await asyncio.wait_for(state.client.snapshot_pane(), timeout=_PANE_CAPTURE_TIMEOUT_S)
    except (TimeoutError, OSError, RuntimeError):
        return ""
    if not pane:
        return ""
    return format_pane_tail(pane)


async def sdk_watchdog(state: vm.State, *, stop: asyncio.Event) -> None:
    warned_at: set[int] = set()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
            break
        except TimeoutError:
            pass
        idle = sdk_idle_seconds(state)
        for threshold in _WATCHDOG_THRESHOLDS_S:
            if idle >= threshold and threshold not in warned_at:
                warned_at.add(threshold)
                alive = _check_sdk_subprocess_alive(state)
                alive_str = f"process_alive={alive}" if alive is not None else "process_alive=unknown"
                diag = format_hang_diagnostics(state)
                msg = f"SDK silent for {threshold}s | {alive_str} | {diag}"
                # Only escalate when something is actually wrong: the alive check returned
                # False (verified subprocess death), OR a turn is in flight with no tool
                # running. A tool actively executing (a long build, a `sleep`, a subagent)
                # fully explains the silence: the SDK is busy doing real work, not hung,
                # so a foreground `sleep 180` should not look like a stall. This mirrors
                # attempt_interrupt (client.py), which likewise refuses to act while a tool
                # is in flight. Otherwise the SDK is just idle; log at debug so quiet
                # stretches (between turns, or mid-tool) don't spam the warning stream.
                turn_in_flight = state.interrupt_event is not None
                tool_running = bool(state.active_tools)
                if alive is False or (turn_in_flight and not tool_running):
                    pane_tail = await _capture_pane_tail(state)
                    if pane_tail:
                        msg = f"{msg} | pane_tail={pane_tail!r}"
                    logger.warning(msg)
                    # One event per threshold crossing (warned_at gates re-emit), so a multi-minute
                    # hang reaches the observability surface without spamming the stream every poll.
                    state.event_bus.emit({"type": "error", "text": msg})
                else:
                    logger.debug(msg)
        if idle < _WATCHDOG_THRESHOLDS_S[0]:
            warned_at.clear()


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
    except (OSError, RuntimeError, KeyError, TypeError):
        pass
