import typing as tp

from claude_agent_sdk import HookMatcher, HookContext
from claude_agent_sdk.types import HookInput, HookJSONOutput, HookEvent, HookCallback

from vesta import logger


async def log_tool_start(input_data: HookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
    tool_name = input_data["tool_name"] if "tool_name" in input_data else "unknown"
    logger.tool(f"start: {tool_name}")
    if tool_name == "Task":
        tool_input = input_data["tool_input"] if "tool_input" in input_data else None
        if isinstance(tool_input, dict) and "subagent_type" in tool_input:
            logger.subagent(f"spawn: {tool_input['subagent_type']}")
    return tp.cast(HookJSONOutput, {})


async def log_tool_finish(input_data: HookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
    tool_name = input_data["tool_name"] if "tool_name" in input_data else "unknown"
    logger.tool(f"done: {tool_name}")
    return tp.cast(HookJSONOutput, {})


def build_hooks() -> dict[HookEvent, list[HookMatcher]]:
    return {
        "PreToolUse": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_start)])],
        "PostToolUse": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_finish)])],
    }
