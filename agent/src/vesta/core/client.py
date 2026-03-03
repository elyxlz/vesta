import asyncio
import datetime as dt
import json
import os
import signal
import typing as tp

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    HookContext,
    Message,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    tool,
    create_sdk_mcp_server,
)
from claude_agent_sdk.types import PreToolUseHookInput, PostToolUseHookInput, HookJSONOutput, HookCallback

import vesta.models as vm
from vesta import logger
from vesta.core.init import get_memory_path, build_restart_context


def _build_query(prompt: str, *, timestamp: dt.datetime) -> str:
    timestamp_str = timestamp.strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")
    return f"[Current time: {timestamp_str}]\n{prompt}"


def _format_tool_call(name: str, *, input_data: object, sub_agent_context: str | None) -> tuple[str, str | None]:
    input_str = json.dumps(input_data) if isinstance(input_data, dict) else str(input_data)
    input_preview = (input_str[:150] + "...") if len(input_str) > 150 else input_str

    if name == "Task":
        if isinstance(input_data, dict):
            data = tp.cast(dict[str, tp.Any], input_data)
            agent_type = data["subagent_type"] if "subagent_type" in data else "unknown"
            description = data["description"] if "description" in data else ""
        else:
            agent_type = "unknown"
            description = ""
        return f"[TASK] [{agent_type}]: {description or input_preview}", agent_type

    prefix = f"[{sub_agent_context}] " if sub_agent_context else ""
    return f"[TOOL] {prefix}{name}: {input_preview}", sub_agent_context


def filter_tool_lines(text: str) -> str:
    return "\n".join(
        s for line in text.split("\n")
        if (s := line.strip()) and not s.startswith("[TOOL]") and not s.startswith("[TASK]")
    )


def _parse_sdk_message(msg: Message, *, sub_agent_context: str | None) -> tuple[list[str], str | None, str | None, bool]:
    if isinstance(msg, ResultMessage):
        session_id: str | None = None
        try:
            session_id = msg.session_id
        except AttributeError:
            pass
        return ([], sub_agent_context, session_id, False)

    if not isinstance(msg, AssistantMessage):
        return ([msg] if isinstance(msg, str) else [], sub_agent_context, None, False)

    texts = []
    has_task_result = False
    has_tool_use = False
    current_context = sub_agent_context

    for block in msg.content:
        if isinstance(block, TextBlock):
            text = block.text
            if current_context and "completed" in text.lower():
                has_task_result = True
            texts.append(text)
        elif isinstance(block, ToolUseBlock):
            has_tool_use = True
            formatted, new_context = _format_tool_call(block.name, input_data=block.input, sub_agent_context=current_context)
            texts.append(formatted)
            if new_context:
                current_context = new_context

    if has_task_result and current_context:
        current_context = None

    return texts, current_context, None, has_tool_use


_TOOL_KEYS: dict[str, str] = {
    "Bash": "command",
    "Skill": "skill",
    "Read": "file_path",
    "Write": "file_path",
    "Edit": "file_path",
    "Glob": "pattern",
    "Grep": "pattern",
}


def _tool_summary(name: str, tool_input: dict[str, tp.Any]) -> str:
    if name == "Task":
        agent = tool_input["subagent_type"] if "subagent_type" in tool_input else "?"
        desc = tool_input["description"] if "description" in tool_input else ""
        return f"Task [{agent}]: {desc}"
    if name in _TOOL_KEYS:
        val = tool_input[_TOOL_KEYS[name]] if _TOOL_KEYS[name] in tool_input else "?"
        preview = (val[:120] + "...") if len(val) > 120 else val
        return f"{name}: {preview}"
    raw = json.dumps(tool_input)
    preview = (raw[:100] + "...") if len(raw) > 100 else raw
    return f"{name}: {preview}"


def _make_tool_hooks(state: vm.State) -> tuple[HookCallback, HookCallback]:
    async def log_tool_start(input_data: PreToolUseHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        name = input_data["tool_name"]
        summary = _tool_summary(name, input_data["tool_input"])
        logger.tool(summary)
        state.event_bus.set_state("tool_use")
        state.event_bus.emit({"type": "tool_start", "tool": name, "input": summary})
        return tp.cast(HookJSONOutput, {})

    async def log_tool_finish(input_data: PostToolUseHookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
        name = input_data["tool_name"]
        logger.tool(f"done: {name}")
        state.event_bus.emit({"type": "tool_end", "tool": name})
        state.event_bus.set_state("thinking")
        return tp.cast(HookJSONOutput, {})

    return tp.cast(HookCallback, log_tool_start), tp.cast(HookCallback, log_tool_finish)


async def attempt_interrupt(state: vm.State, *, config: vm.VestaConfig, reason: str) -> bool:
    logger.interrupt(f"Starting interrupt attempt: {reason}")

    client = state.client
    if not client:
        logger.interrupt("No client, aborting")
        return False

    try:
        await asyncio.wait_for(client.interrupt(), timeout=config.interrupt_timeout)
        logger.interrupt(f"{reason}: interrupt sent")
        return True
    except TimeoutError:
        logger.error("SDK unresponsive, sending SIGTERM for graceful shutdown")
        try:
            (config.data_dir / "crash_reason").write_text("SDK became unresponsive (interrupt timed out)")
        except OSError:
            pass
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(10)
        os._exit(1)
    except (OSError, RuntimeError) as e:
        logger.error(f"Interrupt failed: {e}")
        return False


def persist_session_id(session_id: str, *, state: vm.State, config: vm.VestaConfig) -> None:
    state.session_id = session_id
    config.session_file.parent.mkdir(parents=True, exist_ok=True)
    config.session_file.write_text(session_id)
    logger.debug(f"Captured session_id: {session_id[:16]}...")


async def converse(prompt: str, *, state: vm.State, config: vm.VestaConfig, show_output: bool) -> list[str]:
    assert state.client is not None
    client = state.client

    query = _build_query(prompt, timestamp=dt.datetime.now())
    try:
        await asyncio.wait_for(client.query(query), timeout=config.query_timeout)
    except TimeoutError:
        await attempt_interrupt(state, config=config, reason="Query timeout")
        raise

    responses: list[str] = []
    sub_agent_context: str | None = None
    response_iter = client.receive_response().__aiter__()

    while True:
        try:
            msg = await asyncio.wait_for(response_iter.__anext__(), timeout=config.response_timeout)
        except StopAsyncIteration:
            break
        except TimeoutError:
            await attempt_interrupt(state, config=config, reason="Response timeout")
            raise

        texts, sub_agent_context, session_id, has_tool_use = _parse_sdk_message(msg, sub_agent_context=sub_agent_context)
        if session_id and session_id != state.session_id:
            persist_session_id(session_id, state=state, config=config)
        text = "\n".join(texts) if texts else None
        if not text:
            continue
        if not show_output:
            responses.append(text)
            continue
        filtered = filter_tool_lines(text)
        if filtered and not has_tool_use:
            logger.assistant(filtered)
            state.event_bus.emit({"type": "assistant", "text": filtered})

    return responses


async def process_message(msg: str, *, state: vm.State, config: vm.VestaConfig, is_user: bool) -> tuple[list[str], vm.State]:
    responses = await converse(msg, state=state, config=config, show_output=is_user)
    return responses, state


def _build_vesta_tools_server(state: vm.State, config: vm.VestaConfig) -> tp.Any:
    @tool("restart_vesta", "Restart to reload memory, skills, and prompts. Current conversation is preserved.", {})
    async def restart_vesta(args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        if state.graceful_shutdown and state.graceful_shutdown.is_set():
            if state.shutdown_event:
                state.shutdown_event.set()
            return {"content": [{"type": "text", "text": "Shutdown complete. Sweet dreams."}]}
        state.pending_context = build_restart_context("self restart — memory, skills, and prompts refreshed", config)
        return {"content": [{"type": "text", "text": "Restart initiated. Session will resume with refreshed configuration."}]}

    return create_sdk_mcp_server("vesta-tools", tools=[restart_vesta])


def build_client_options(config: vm.VestaConfig, state: vm.State) -> ClaudeAgentOptions:
    memory_path = get_memory_path(config)
    system_prompt = memory_path.read_text()

    name = config.agent_name
    system_prompt = f"Your name is {name}.\n\n{system_prompt}"

    pre_hook, post_hook = _make_tool_hooks(state)

    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        hooks={
            "PreToolUse": [HookMatcher(hooks=[pre_hook])],
            "PostToolUse": [HookMatcher(hooks=[post_hook])],
        },
        permission_mode="bypassPermissions",
        cwd=config.state_dir,
        setting_sources=["project"],
        add_dirs=[str(config.state_dir), str(config.skills_dir)],
        max_thinking_tokens=config.max_thinking_tokens,
        max_buffer_size=10 * 1024 * 1024,
        stderr=lambda line: logger.sdk(line),
        mcp_servers={"vesta": _build_vesta_tools_server(state, config)},
        resume=state.session_id,
    )
