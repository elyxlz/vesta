import asyncio

from claude_agent_sdk import ClaudeAgentOptions, Message, tool, create_sdk_mcp_server

import vesta.models as vm
import vesta.utils as vu
import vesta.core.effects as vfx
from vesta import logger
from vesta.hooks import build_hooks
from vesta.core.dreamer import load_memory


def load_system_prompt(config: vm.VestaConfig) -> str:
    return load_memory(config)


async def attempt_interrupt(state: vm.State, *, config: vm.VestaConfig, reason: str) -> bool:
    logger.interrupt(f"Starting interrupt attempt: {reason}")

    if not state.client:
        logger.interrupt("No client, aborting")
        return False

    try:
        await asyncio.wait_for(state.client.interrupt(), timeout=config.interrupt_timeout)
        logger.interrupt(f"{reason}: interrupt sent")
        return True
    except TimeoutError:
        logger.interrupt("Interrupt timed out")
        return False


def parse_assistant_message(msg: Message, *, state: vm.State, sub_agent_context: str | None) -> tuple[str | None, str | None]:
    texts, new_context, session_id = vu.parse_assistant_message(msg, sub_agent_context=sub_agent_context)
    if session_id:
        state.session_id = session_id
        logger.debug(f"Captured session_id: {session_id[:16]}...")
    return "\n".join(texts) if texts else None, new_context


async def converse(prompt: str, *, state: vm.State, config: vm.VestaConfig, show_output: bool) -> list[str]:
    assert state.client is not None
    client = state.client

    timestamp = vfx.get_current_time()
    query_with_context = vu.build_query_with_timestamp(prompt, timestamp=timestamp)
    await asyncio.wait_for(client.query(query_with_context), timeout=config.query_timeout)

    responses: list[str] = []
    sub_agent_context: str | None = None

    async def collect() -> None:
        nonlocal sub_agent_context
        async for msg in client.receive_response():
            text, sub_agent_context = parse_assistant_message(msg, state=state, sub_agent_context=sub_agent_context)
            if not text:
                continue
            if not show_output:
                responses.append(text)
                continue
            for line in text.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("[TOOL]") or stripped.startswith("[TASK]"):
                    logger.tool(stripped)
                else:
                    logger.assistant(stripped)

    try:
        await asyncio.wait_for(collect(), timeout=config.response_timeout)
    except TimeoutError:
        responses.append("[Response timeout]")
        await attempt_interrupt(state, config=config, reason="Response timeout")

    return responses


async def process_message(msg: str, *, state: vm.State, config: vm.VestaConfig, is_user: bool) -> tuple[list[str], vm.State]:
    responses = await converse(msg, state=state, config=config, show_output=is_user)
    return responses, state


def build_vesta_tools_server(state: vm.State):
    @tool("restart_vesta", "Restart Vesta to reload system prompt, skills, and memory files. Current conversation is preserved.", {})
    async def restart_vesta(args):
        state.pending_context = "[System: Vesta restarted. Configuration and system prompt refreshed. Previous conversation resumed.]"
        return {"content": [{"type": "text", "text": "Restart initiated. Session will resume with refreshed configuration."}]}

    return create_sdk_mcp_server("vesta-tools", tools=[restart_vesta])


def build_client_options(config: vm.VestaConfig, state: vm.State) -> ClaudeAgentOptions:
    def handle_stderr(line: str) -> None:
        logger.sdk(line)

    return ClaudeAgentOptions(
        system_prompt=load_system_prompt(config),
        hooks=build_hooks(),
        permission_mode="bypassPermissions",
        cwd=config.state_dir,
        setting_sources=["project"],
        add_dirs=[str(config.state_dir), str(config.skills_dir)],
        max_thinking_tokens=config.max_thinking_tokens,
        max_buffer_size=10 * 1024 * 1024,
        stderr=handle_stderr,
        mcp_servers={"vesta": build_vesta_tools_server(state)},
        resume=state.session_id,
    )
