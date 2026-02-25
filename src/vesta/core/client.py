import asyncio

from claude_agent_sdk import ClaudeAgentOptions, Message

import vesta.models as vm
import vesta.utils as vu
import vesta.core.effects as vfx
from vesta import logger
from vesta.hooks import build_hooks
from vesta.core.dreamer import load_memory
from vesta.core.io import output_line


def load_system_prompt(config: vm.VestaConfig) -> str:
    return load_memory(config)


async def attempt_interrupt(state: vm.State, *, config: vm.VestaConfig, reason: str) -> bool:
    logger.interrupt(f"Starting interrupt attempt: {reason}")

    if not state.client:
        logger.interrupt("No client, aborting")
        return False

    logger.interrupt("Sending interrupt to client (receive_response will complete naturally)")

    try:
        logger.interrupt("Calling state.client.interrupt()")
        await asyncio.wait_for(state.client.interrupt(), timeout=config.interrupt_timeout)
        logger.interrupt("state.client.interrupt() returned successfully")

        logger.interrupt(f"{reason}: interrupt sent")

        return True

    except TimeoutError:
        logger.interrupt("Interrupt timed out; client likely still running")
        return False


def parse_assistant_message(msg: Message, *, state: vm.State) -> tuple[str | None, vm.State]:
    texts, new_context, session_id = vu.parse_assistant_message(msg, sub_agent_context=state.sub_agent_context)
    state.sub_agent_context = new_context
    if session_id:
        state.session_id = session_id
        logger.debug(f"Captured session_id: {session_id[:16]}...")
    return "\n".join(texts) if texts else None, state


async def converse(prompt: str, *, state: vm.State, config: vm.VestaConfig, show_output: bool) -> list[str]:
    assert state.client is not None
    client = state.client

    timestamp = vfx.get_current_time()
    query_with_context = vu.build_query_with_timestamp(prompt, timestamp=timestamp)
    logger.debug(f"Sending query ({len(query_with_context)} chars)")
    await asyncio.wait_for(client.query(query_with_context), timeout=30.0)

    responses: list[str] = []

    async def collect() -> None:
        async for msg in client.receive_response():
            text, _ = parse_assistant_message(msg, state=state)
            if not text:
                continue
            lines = [line for line in text.split("\n") if line.strip()]
            if not show_output:
                responses.extend(lines)
                continue
            for line in lines:
                if line.startswith("[TOOL]") or line.startswith("[TASK]"):
                    await output_line(line, is_tool=True)
                else:
                    responses.append(line)

    try:
        await asyncio.wait_for(collect(), timeout=config.response_timeout)
    except TimeoutError:
        responses.append("[Response timeout]")
        state.sub_agent_context = None
        await attempt_interrupt(state, config=config, reason="Response timeout")

    return responses


async def process_message(msg: str, *, state: vm.State, config: vm.VestaConfig, is_user: bool) -> tuple[list[str], vm.State]:
    logger.debug(f"Processing message (is_user={is_user})")
    responses = await converse(msg, state=state, config=config, show_output=is_user)
    logger.debug(f"Got {len(responses)} responses")
    return responses, state


def build_client_options(config: vm.VestaConfig, state: vm.State) -> ClaudeAgentOptions:
    def handle_stderr(line: str) -> None:
        logger.sdk(line)

    return ClaudeAgentOptions(
        system_prompt=load_system_prompt(config),
        hooks=build_hooks(state),
        permission_mode="bypassPermissions",
        cwd=config.state_dir,
        setting_sources=["project"],
        add_dirs=[str(config.state_dir), str(config.skills_dir)],
        max_thinking_tokens=config.max_thinking_tokens,
        max_buffer_size=10 * 1024 * 1024,
        stderr=handle_stderr,
    )
