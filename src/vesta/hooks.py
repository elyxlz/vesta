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


async def log_tool_finish(input_data: HookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
    tool = input_data.get("tool_name", "unknown")
    logger.tool(f"done: {tool}")
    return tp.cast(HookJSONOutput, {})


def build_hooks(state: vm.State) -> dict[HookEvent, list[HookMatcher]]:
    return {
        "PreToolUse": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_start)])],
        "PostToolUse": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_finish)])],
    }
