import typing as tp

from claude_agent_sdk import HookMatcher, HookContext
from claude_agent_sdk.types import HookInput, HookJSONOutput, HookEvent, HookCallback

from vesta.agents import AGENT_NAMES
import vesta.models as vm
from vesta.effects import logger


async def log_tool_start(input_data: HookInput, *, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
    tool = input_data.get("tool_name", "unknown")
    logger.info(f"TOOL start: {tool}")
    if tool == "Task":
        tool_input = input_data.get("tool_input")
        if isinstance(tool_input, dict):
            subagent = tool_input.get("subagent_type")
            if subagent:
                logger.info(f"SUBAGENT spawn: {subagent}")
    return {}


def build_hooks(state: vm.State) -> dict[HookEvent, list[HookMatcher]]:
    async def log_tool_finish(input_data: HookInput, *, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        tool = input_data.get("tool_name", "unknown")
        logger.info(f"TOOL done: {tool}")

        if tool == "Task":
            tool_input = input_data.get("tool_input")
            tool_response = input_data.get("tool_response", "")
            if isinstance(tool_input, dict):
                subagent_type = tool_input.get("subagent_type")
                if subagent_type and subagent_type in AGENT_NAMES and tool_response:
                    async with state.subagent_conversations_lock:
                        if subagent_type not in state.subagent_conversations:
                            state.subagent_conversations[subagent_type] = []
                        state.subagent_conversations[subagent_type].append(str(tool_response))
                    logger.info(f"SUBAGENT response captured: {subagent_type}")

        return {}

    return {
        "PreToolUse": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_start)])],
        "PostToolUse": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_finish)])],
    }
