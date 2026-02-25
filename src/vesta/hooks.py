import typing as tp

from claude_agent_sdk import HookMatcher, HookContext
from claude_agent_sdk.types import PreToolUseHookInput, PostToolUseHookInput, HookJSONOutput, HookEvent, HookCallback

from vesta import logger


async def log_tool_start(input_data: PreToolUseHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
    logger.tool(f"start: {input_data['tool_name']}")
    if input_data["tool_name"] == "Task":
        tool_input = input_data["tool_input"]
        if "subagent_type" in tool_input:
            logger.subagent(f"spawn: {tool_input['subagent_type']}")
    return tp.cast(HookJSONOutput, {})


async def log_tool_finish(input_data: PostToolUseHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
    logger.tool(f"done: {input_data['tool_name']}")
    return tp.cast(HookJSONOutput, {})


def build_hooks() -> dict[HookEvent, list[HookMatcher]]:
    return {
        "PreToolUse": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_start)])],
        "PostToolUse": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_finish)])],
    }
