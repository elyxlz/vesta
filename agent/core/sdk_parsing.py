"""SDK message parsing, tool-call rendering, and the hook callback factory."""

import datetime as dt
import json
import time
import typing as tp
from collections.abc import Mapping

from claude_agent_sdk import (
    AssistantMessage,
    HookContext,
    HookMatcher,
    Message,
    RateLimitEvent,
    RateLimitInfo,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
)
from claude_agent_sdk.types import (
    HookCallback,
    HookEvent,
    HookJSONOutput,
    NotificationHookInput,
    PostToolUseFailureHookInput,
    PostToolUseHookInput,
    PreCompactHookInput,
    PreToolUseHookInput,
    StopHookInput,
    SubagentStartHookInput,
    SubagentStopHookInput,
)

from . import diagnostics, logger
from . import models as vm
from .events import StreamEvent

_AGENT_TOOLS = ("Task", "Agent")

_TOOL_KEYS: dict[str, str] = {
    "Bash": "command",
    "Skill": "skill",
    "Read": "file_path",
    "Write": "file_path",
    "Edit": "file_path",
    "Glob": "pattern",
    "Grep": "pattern",
}


def build_query(prompt: str, *, timestamp: dt.datetime) -> str:
    if prompt.startswith("/"):
        return prompt
    timestamp_str = timestamp.strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")
    return f"[Current time: {timestamp_str}]\n{prompt}"


def build_priority_now_message(prompt: str, *, timestamp: dt.datetime) -> dict[str, tp.Any]:
    """The stream-json envelope for a preempting user message. `priority` is undocumented CLI
    protocol (verified on 2.1.191/2.1.201, probed live 2026-07-06): a queued "now" prompt makes
    the CLI end the running turn at its next step boundary with the graceful "interrupt" reason,
    so background subagents survive — unlike the interrupt control request, whose headless
    handler kills every backgrounded task (issue #982). A CLI that ignores the field just queues
    the message to run after the current turn: delayed, never lost."""
    return {
        "type": "user",
        "message": {"role": "user", "content": build_query(prompt, timestamp=timestamp)},
        "parent_tool_use_id": None,
        "priority": "now",
    }


_RATE_LIMIT_WINDOWS: dict[str, str] = {
    "five_hour": "5-hour usage window",
    "seven_day": "weekly usage window",
    "seven_day_opus": "weekly Opus usage window",
    "seven_day_sonnet": "weekly Sonnet usage window",
    "overage": "extra usage budget",
}
_ROLLING_WINDOW_NOTE = " This is the rolling usage limit, not a spend or billing limit."


def rate_limit_notice(info: RateLimitInfo, *, now: float) -> str | None:
    """User-facing wording for a rejected rate limit, built from the CLI's structured
    classification. The CLI's own text for the same rejection is a paraphrase (observed calling a
    five_hour rejection a "monthly spend limit", issue #1071), so consumers get this instead."""
    if info.status != "rejected":
        return None
    reset = ""
    if info.resets_at is not None and info.resets_at > now:
        remaining = int(info.resets_at - now)
        hours, minutes = remaining // 3600, remaining % 3600 // 60
        parts = ([f"{hours}h"] if hours else []) + ([f"{minutes}m"] if minutes or not hours else [])
        reset = f", resets in {' '.join(parts)}"
    if info.rate_limit_type not in _RATE_LIMIT_WINDOWS:
        return f"Claude rate limit hit{reset}."
    window = _RATE_LIMIT_WINDOWS[info.rate_limit_type]
    note = "" if info.rate_limit_type == "overage" else _ROLLING_WINDOW_NOTE
    return f"Claude rate limit hit: the {window} is exhausted{reset}.{note}"


def thinking_tokens_estimate(msg: Message) -> int | None:
    """The CLI streams SystemMessage(subtype="thinking_tokens") counters throughout extended
    thinking. Return the running token estimate, or None for any other message (or a payload
    without the expected int field)."""
    if not isinstance(msg, SystemMessage) or msg.subtype != "thinking_tokens":
        return None
    if isinstance(msg.data, dict) and "estimated_tokens" in msg.data and isinstance(msg.data["estimated_tokens"], int):
        return msg.data["estimated_tokens"]
    return None


def filter_tool_lines(text: str) -> str:
    return "\n".join(s for line in text.split("\n") if (s := line.strip()) and not s.startswith("[TOOL]") and not s.startswith("[TASK]"))


def _is_cli_error_text(text: str) -> bool:
    """CLI-synthesized error strings arrive as assistant text blocks (an 'API Error:' prefix or the
    bare 'Prompt is too long'); they are operational noise, not Vesta's speech, so parse routes them
    to the error channel instead of published texts (same principle as rate_limit_notice replacing
    the CLI's raw text)."""
    return text.startswith("API Error:") or text == "Prompt is too long"


def _parse_agent_input(input_data: object) -> tuple[str, str]:
    if isinstance(input_data, dict):
        data = tp.cast(dict[str, tp.Any], input_data)
        agent_type = data["subagent_type"] if "subagent_type" in data else "unknown"
        description = data["description"] if "description" in data else ""
    else:
        agent_type = "unknown"
        description = ""
    return agent_type, description


_ParsedMessage = tuple[list[str], list[ThinkingBlock], str | None, list[str]]


def _log_result_usage(msg: ResultMessage) -> None:
    usage_data = msg.usage or {}
    parts = []
    if usage_data:
        input_tok = usage_data["input_tokens"] if "input_tokens" in usage_data else 0
        output_tok = usage_data["output_tokens"] if "output_tokens" in usage_data else 0
        cache_read = usage_data["cache_read_input_tokens"] if "cache_read_input_tokens" in usage_data else 0
        cache_create = usage_data["cache_creation_input_tokens"] if "cache_creation_input_tokens" in usage_data else 0
        parts.append(f"in={input_tok} out={output_tok} cache_read={cache_read} cache_write={cache_create}")
    if msg.total_cost_usd is not None:
        parts.append(f"cost=${msg.total_cost_usd:.4f}")
    parts.append(f"duration={msg.duration_ms / 1000:.1f}s")
    logger.usage(" | ".join(parts))


def _parse_system_message(msg: SystemMessage) -> _ParsedMessage:
    if msg.subtype == "init":
        # The init message carries the session_id first, before any ResultMessage. Return it so
        # the caller persists it immediately: a fresh turn that crashes before completing can
        # still be resumed (the official client exposes no session_id attribute to fall back on).
        init_sid = msg.data["session_id"] if isinstance(msg.data, dict) and "session_id" in msg.data else None
        if init_sid:
            logger.debug(f"[init] session_id={init_sid[:16]}")
        return [], [], init_sid, []
    # thinking_tokens is a per-delta streaming counter the SDK emits dozens of times per turn; it
    # floods the log with no signal here (thinking_tokens_estimate exposes it for liveness notes).
    if msg.subtype == "thinking_tokens":
        return [], [], None, []
    if msg.subtype == "compact_boundary":
        logger.client("Compaction boundary reached")
        return [], [], None, []
    raw = json.dumps(msg.data, default=str)
    logger.system(f"[{msg.subtype}] {raw[:2000]}")
    return [], [], None, []


def _parse_assistant_message(msg: AssistantMessage) -> _ParsedMessage:
    texts = []
    thinking_blocks = []
    error_texts = []
    for block in msg.content:
        if isinstance(block, TextBlock):
            if _is_cli_error_text(block.text):
                logger.warning(f"Suppressed CLI-synthesized error text from assistant output: {block.text[:500]}")
                error_texts.append(block.text)
                continue
            texts.append(block.text)
        elif isinstance(block, ThinkingBlock):
            thinking_blocks.append(block)
    return texts, thinking_blocks, None, error_texts


def parse_sdk_message(msg: Message) -> _ParsedMessage:
    """Extract assistant text + thinking blocks (and a session_id from a ResultMessage) from one SDK
    message. CLI-synthesized error text (_is_cli_error_text) is kept out of the speech texts and
    returned in the final element so the caller surfaces it through the error channel. Tool-use
    blocks carry no output here: tool/subagent activity is surfaced via the native hooks in
    make_hooks, so they are ignored. Non-assistant messages just log and return empties."""
    if isinstance(msg, ResultMessage):
        _log_result_usage(msg)
        return [], [], msg.session_id, []
    if isinstance(msg, RateLimitEvent):
        info = msg.rate_limit_info
        log_fn = logger.debug if info.status == "allowed" else logger.warning
        log_fn(f"Rate limit {info.status} (utilization={info.utilization}, type={info.rate_limit_type})")
        return [], [], None, []
    if isinstance(msg, SystemMessage):
        return _parse_system_message(msg)
    if not isinstance(msg, AssistantMessage):
        return [], [], None, []
    return _parse_assistant_message(msg)


def _tool_summary(name: str, tool_input: dict[str, tp.Any]) -> str:
    if name in _AGENT_TOOLS:
        agent_type, description = _parse_agent_input(tool_input)
        return f"Task [{agent_type}]: {description}"
    if name in _TOOL_KEYS:
        val = tool_input[_TOOL_KEYS[name]] if _TOOL_KEYS[name] in tool_input else "?"
        return f"{name}: {val}"
    return f"{name}: {json.dumps(tool_input)}"


def _subagent_hook(state: vm.State, *, verb: str, event_type: str) -> HookCallback:
    async def hook(
        input_data: SubagentStartHookInput | SubagentStopHookInput, _tool_use_id: str | None, _context: HookContext
    ) -> HookJSONOutput:
        agent_id = input_data["agent_id"] if "agent_id" in input_data else "?"
        agent_type = input_data["agent_type"] if "agent_type" in input_data else "unknown"
        logger.subagent(f"{verb} [{agent_type}] id={agent_id}")
        state.event_bus.emit(tp.cast(StreamEvent, {"type": event_type, "agent_id": agent_id, "agent_type": agent_type}))
        return tp.cast(HookJSONOutput, {})

    return tp.cast(HookCallback, hook)


def _subagent_prefix(input_data: Mapping[str, object]) -> tuple[str, bool]:
    """Extract sub-agent prefix from hook input. SDK adds agent_id/agent_type for sub-agent calls."""
    if "agent_id" not in input_data:
        return "", False
    agent_type = input_data["agent_type"] if "agent_type" in input_data else None
    prefix = f"[SUB:{agent_type}] " if agent_type else "[SUB] "
    return prefix, True


def make_hooks(state: vm.State) -> dict[HookEvent, list[HookMatcher]]:
    async def log_tool_start(input_data: PreToolUseHookInput, tool_use_id: str | None, _context: HookContext) -> HookJSONOutput:
        name = input_data["tool_name"] if "tool_name" in input_data else "?"
        summary = _tool_summary(name, input_data["tool_input"] if "tool_input" in input_data else {})
        prefix, is_sub = _subagent_prefix(input_data)
        logger.tool(f"{prefix}{summary}")
        state.event_bus.emit({"type": "tool_start", "tool": name, "input": summary, "subagent": is_sub})
        diagnostics.touch_activity(state, f"tool_start:{name}")
        tool_id = tool_use_id or name
        state.active_tools[tool_id] = vm.ActiveTool(name=name, summary=summary, started_at=time.monotonic(), is_subagent=is_sub)
        return tp.cast(HookJSONOutput, {})

    async def log_tool_finish(input_data: PostToolUseHookInput, tool_use_id: str | None, _context: HookContext) -> HookJSONOutput:
        name = input_data["tool_name"] if "tool_name" in input_data else "?"
        prefix, is_sub = _subagent_prefix(input_data)
        tool_id = tool_use_id or name
        elapsed = ""
        active = state.active_tools.pop(tool_id, None)
        if active:
            duration = time.monotonic() - active.started_at
            elapsed = f" ({duration:.1f}s)"
        logger.tool(f"{prefix}done: {name}{elapsed}")
        state.event_bus.emit({"type": "tool_end", "tool": name, "subagent": is_sub})
        diagnostics.touch_activity(state, f"tool_end:{name}")
        return tp.cast(HookJSONOutput, {})

    async def log_tool_failure(input_data: PostToolUseFailureHookInput, tool_use_id: str | None, _context: HookContext) -> HookJSONOutput:
        name = input_data["tool_name"] if "tool_name" in input_data else "?"
        error = input_data["error"] if "error" in input_data else "(unknown error)"
        prefix, is_sub = _subagent_prefix(input_data)
        logger.warning(f"{prefix}Tool failed: {name}: {error}")
        state.event_bus.emit({"type": "tool_end", "tool": name, "subagent": is_sub})
        tool_id = tool_use_id or name
        state.active_tools.pop(tool_id, None)
        diagnostics.touch_activity(state, f"tool_fail:{name}")
        return tp.cast(HookJSONOutput, {})

    async def log_compact(input_data: PreCompactHookInput, _tool_use_id: str | None, _context: HookContext) -> HookJSONOutput:
        trigger = input_data["trigger"] if "trigger" in input_data else "unknown"
        state.compacting = True
        logger.client(f"Context compaction starting (trigger={trigger})")
        return tp.cast(HookJSONOutput, {})

    async def log_notification(input_data: NotificationHookInput, _tool_use_id: str | None, _context: HookContext) -> HookJSONOutput:
        title = input_data["title"] if "title" in input_data else None
        prefix = f"{title}: " if title else ""
        kind = input_data["notification_type"] if "notification_type" in input_data else "notification"
        message = input_data["message"] if "message" in input_data else ""
        logger.system(f"[{kind}] {prefix}{message}")
        return tp.cast(HookJSONOutput, {})

    async def log_stop(_input_data: StopHookInput, _tool_use_id: str | None, _context: HookContext) -> HookJSONOutput:
        logger.client("Agent execution stopped")
        return tp.cast(HookJSONOutput, {})

    return {
        "PreToolUse": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_start)])],
        "PostToolUse": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_finish)])],
        "PostToolUseFailure": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_failure)])],
        "SubagentStart": [HookMatcher(hooks=[_subagent_hook(state, verb="started", event_type="subagent_start")])],
        "SubagentStop": [HookMatcher(hooks=[_subagent_hook(state, verb="stopped", event_type="subagent_stop")])],
        "PreCompact": [HookMatcher(hooks=[tp.cast(HookCallback, log_compact)])],
        "Notification": [HookMatcher(hooks=[tp.cast(HookCallback, log_notification)])],
        "Stop": [HookMatcher(hooks=[tp.cast(HookCallback, log_stop)])],
    }
