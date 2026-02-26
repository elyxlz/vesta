import json
import typing as tp

from claude_agent_sdk import HookMatcher, HookContext
from claude_agent_sdk.types import PreToolUseHookInput, PostToolUseHookInput, HookJSONOutput, HookEvent, HookCallback

from vesta import logger


def _tool_summary(name: str, tool_input: dict[str, tp.Any]) -> str:
    if name == "Bash":
        cmd = tool_input["command"] if "command" in tool_input else ""
        preview = (cmd[:120] + "...") if len(cmd) > 120 else cmd
        return f"Bash: {preview}"
    if name == "Skill":
        return f"Skill: {tool_input['skill'] if 'skill' in tool_input else '?'}"
    if name == "Read":
        return f"Read: {tool_input['file_path'] if 'file_path' in tool_input else '?'}"
    if name == "Write":
        return f"Write: {tool_input['file_path'] if 'file_path' in tool_input else '?'}"
    if name == "Edit":
        return f"Edit: {tool_input['file_path'] if 'file_path' in tool_input else '?'}"
    if name == "Glob":
        return f"Glob: {tool_input['pattern'] if 'pattern' in tool_input else '?'}"
    if name == "Grep":
        return f"Grep: {tool_input['pattern'] if 'pattern' in tool_input else '?'}"
    if name == "Task":
        agent = tool_input["subagent_type"] if "subagent_type" in tool_input else "?"
        desc = tool_input["description"] if "description" in tool_input else ""
        return f"Task [{agent}]: {desc}"
    raw = json.dumps(tool_input)
    preview = (raw[:100] + "...") if len(raw) > 100 else raw
    return f"{name}: {preview}"


async def log_tool_start(input_data: PreToolUseHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
    logger.tool(_tool_summary(input_data["tool_name"], input_data["tool_input"]))
    return tp.cast(HookJSONOutput, {})


async def log_tool_finish(input_data: PostToolUseHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
    logger.tool(f"done: {input_data['tool_name']}")
    return tp.cast(HookJSONOutput, {})


def build_hooks() -> dict[HookEvent, list[HookMatcher]]:
    return {
        "PreToolUse": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_start)])],
        "PostToolUse": [HookMatcher(hooks=[tp.cast(HookCallback, log_tool_finish)])],
    }
