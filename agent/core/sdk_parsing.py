"""SDK message parsing, tool-call rendering, and the hook callback factory."""

import datetime as dt
import json
import time
import typing as tp
from collections.abc import Mapping

from cc_sdk import (
    AssistantMessage,
    HookContext,
    HookMatcher,
    Message,
    RateLimitEvent,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)
from cc_sdk.types import (
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

from . import diagnostics
from . import logger
from . import models as vm
from .events import StreamEvent, SubagentStartEvent, SubagentStopEvent

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


def filter_tool_lines(text: str) -> str:
    return "\n".join(s for line in text.split("\n") if (s := line.strip()) and not s.startswith("[TOOL]") and not s.startswith("[TASK]"))


def _parse_agent_input(input_data: object) -> tuple[str, str]:
    if isinstance(input_data, dict):
        data = tp.cast(dict[str, tp.Any], input_data)
        agent_type = data["subagent_type"] if "subagent_type" in data else "unknown"
        description = data["description"] if "description" in data else ""
    else:
        agent_type = "unknown"
        description = ""
    return agent_type, description


def _format_tool_call(name: str, *, input_data: object, sub_agent_context: str | None) -> tuple[str, str | None]:
    input_str = json.dumps(input_data) if isinstance(input_data, dict) else str(input_data)

    if name in _AGENT_TOOLS:
        agent_type, description = _parse_agent_input(input_data)
        return f"[TASK] [{agent_type}]: {description or input_str}", agent_type

    prefix = f"[{sub_agent_context}] " if sub_agent_context else ""
    return f"[TOOL] {prefix}{name}: {input_str}", sub_agent_context


def parse_sdk_message(msg: Message, *, sub_agent_context: str | None) -> tuple[list[str], list[ThinkingBlock], str | None, str | None, bool]:
    if isinstance(msg, ResultMessage):
        session_id: str | None = None
        try:
            session_id = msg.session_id
        except AttributeError:
            pass
        try:
            usage_data = msg.usage or {}
            cost = msg.total_cost_usd
            duration_s = msg.duration_ms / 1000 if msg.duration_ms is not None else None
            parts = []
            if usage_data:
                input_tok = usage_data.get("input_tokens", 0)
                output_tok = usage_data.get("output_tokens", 0)
                cache_read = usage_data.get("cache_read_input_tokens", 0)
                cache_create = usage_data.get("cache_creation_input_tokens", 0)
                parts.append(f"in={input_tok} out={output_tok} cache_read={cache_read} cache_write={cache_create}")
            if cost is not None:
                parts.append(f"cost=${cost:.4f}")
            if duration_s is not None:
                parts.append(f"duration={duration_s:.1f}s")
            if parts:
                logger.usage(" | ".join(parts))
        except (AttributeError, TypeError, KeyError):
            pass
        return ([], [], sub_agent_context, session_id, False)

    if isinstance(msg, RateLimitEvent):
        info = msg.rate_limit_info
        log_fn = logger.debug if info.status == "allowed" else logger.warning
        log_fn(f"Rate limit {info.status} (utilization={info.utilization}, type={info.rate_limit_type})")
        return ([], [], sub_agent_context, None, False)

    if isinstance(msg, SystemMessage):
        if msg.subtype == "init":
            sid = msg.data["session_id"][:16] if isinstance(msg.data, dict) and "session_id" in msg.data else "?"
            logger.debug(f"[init] session_id={sid}")
        else:
            raw = json.dumps(msg.data, default=str)
            logger.system(f"[{msg.subtype}] {raw[:500]}")
        return ([], [], sub_agent_context, None, False)

    if not isinstance(msg, AssistantMessage):
        return ([msg] if isinstance(msg, str) else [], [], sub_agent_context, None, False)

    texts = []
    thinking_blocks = []
    has_tool_use = False
    current_context = sub_agent_context

    for block in msg.content:
        if isinstance(block, TextBlock):
            texts.append(block.text)
        elif isinstance(block, ThinkingBlock):
            thinking_blocks.append(block)
        elif isinstance(block, ToolUseBlock):
            has_tool_use = True
            _, new_context = _format_tool_call(block.name, input_data=block.input, sub_agent_context=current_context)
            if new_context:
                current_context = new_context

    return texts, thinking_blocks, current_context, None, has_tool_use


def _tool_summary(name: str, tool_input: dict[str, tp.Any]) -> str:
    if name in _AGENT_TOOLS:
        agent_type, description = _parse_agent_input(tool_input)
        return f"Task [{agent_type}]: {description}"
    if name in _TOOL_KEYS:
        val = tool_input[_TOOL_KEYS[name]] if _TOOL_KEYS[name] in tool_input else "?"
        return f"{name}: {val}"
    raw = json.dumps(tool_input)
    return f"{name}: {raw}"


def _subagent_hook(state: vm.State, *, verb: str, event_type: str) -> HookCallback:
    async def hook(input_data: SubagentStartHookInput | SubagentStopHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        agent_id = input_data["agent_id"]
        agent_type = input_data["agent_type"]
        logger.subagent(f"{verb} [{agent_type}] id={agent_id}")
        event: StreamEvent
        if event_type == "subagent_start":
            event = SubagentStartEvent(type="subagent_start", agent_id=agent_id, agent_type=agent_type)
        else:
            event = SubagentStopEvent(type="subagent_stop", agent_id=agent_id, agent_type=agent_type)
        state.event_bus.emit(event)
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
    async def log_tool_start(input_data: PreToolUseHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        name = input_data["tool_name"]
        summary = _tool_summary(name, input_data["tool_input"])
        prefix, is_sub = _subagent_prefix(input_data)
        logger.tool(f"{prefix}{summary}")
        state.event_bus.emit({"type": "tool_start", "tool": name, "input": summary, "subagent": is_sub})
        diagnostics.touch_activity(state, f"tool_start:{name}")
        tool_id = tool_use_id or name
        state.active_tools[tool_id] = vm.ActiveTool(name=name, summary=summary, started_at=time.monotonic(), is_subagent=is_sub)
        return tp.cast(HookJSONOutput, {})

    async def log_tool_finish(input_data: PostToolUseHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        name = input_data["tool_name"]
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

    async def log_tool_failure(input_data: PostToolUseFailureHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        name = input_data["tool_name"]
        error = input_data["error"]
        prefix, _ = _subagent_prefix(input_data)
        logger.warning(f"{prefix}Tool failed: {name}: {error}")
        tool_id = tool_use_id or name
        state.active_tools.pop(tool_id, None)
        diagnostics.touch_activity(state, f"tool_fail:{name}")
        return tp.cast(HookJSONOutput, {})

    async def log_compact(input_data: PreCompactHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        trigger = input_data["trigger"]
        state.compacting = True
        logger.client(f"Context compaction starting (trigger={trigger})")
        return tp.cast(HookJSONOutput, {})

    async def log_notification(input_data: NotificationHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        title = input_data["title"] if "title" in input_data else None
        prefix = f"{title}: " if title else ""
        logger.system(f"[{input_data['notification_type']}] {prefix}{input_data['message']}")
        return tp.cast(HookJSONOutput, {})

    async def log_stop(input_data: StopHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
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
