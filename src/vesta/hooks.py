import typing as tp

from claude_agent_sdk import HookMatcher, HookContext
from claude_agent_sdk.types import HookInput, HookJSONOutput, HookEvent, HookCallback

import vesta.models as vm
from vesta import logger


async def log_tool_start(input_data: HookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
    tool = input_data.get("tool_name", "unknown")
    logger.tool(f"start: {tool}")
    if tool == "Task":
        tool_input = input_data.get("tool_input")
        if isinstance(tool_input, dict):
            subagent = tool_input.get("subagent_type")
            if subagent:
                logger.subagent(f"spawn: {subagent}")
    return tp.cast(HookJSONOutput, {})


def build_hooks(state: vm.State) -> dict[HookEvent, list[HookMatcher]]:
    async def log_tool_finish(input_data: HookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        tool = input_data.get("tool_name", "unknown")
        logger.tool(f"done: {tool}")

        if tool != "Task":
            return tp.cast(HookJSONOutput, {})

        tool_input = input_data.get("tool_input")
        tool_response = input_data.get("tool_response", "")
        if not isinstance(tool_input, dict):
            return tp.cast(HookJSONOutput, {})

        subagent_type = tool_input.get("subagent_type")
        if not subagent_type or not tool_response:
            return tp.cast(HookJSONOutput, {})

        async with state.subagent_conversations_lock:
            if subagent_type not in state.subagent_conversations:
                state.subagent_conversations[subagent_type] = []
            state.subagent_conversations[subagent_type].append(str(tool_response))
        logger.subagent(f"response captured: {subagent_type}")

        return tp.cast(HookJSONOutput, {})

    return {
        "PreToolUse": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_start)])],
        "PostToolUse": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_finish)])],
    }
