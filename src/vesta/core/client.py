"""Claude SDK client management."""

import asyncio
import os

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, Message

import vesta.models as vm
import vesta.utils as vu
import vesta.core.effects as vfx
from vesta import logger
from vesta.hooks import build_hooks
from vesta.integrations.mcp_registry import build_mcp_servers
from vesta.core.dreamer import load_memory
from vesta.core.io import output_line


def load_system_prompt(config: vm.VestaConfig) -> str:
    """Load main agent's memory as system prompt."""
    return load_memory(config)


async def attempt_interrupt(state: vm.State, *, config: vm.VestaConfig, reason: str) -> bool:
    logger.debug(f"[INTERRUPT] Starting interrupt attempt: {reason}")

    if not state.client:
        logger.debug("[INTERRUPT] No client, aborting")
        return False

    logger.debug("[INTERRUPT] Sending interrupt to client (receive_response will complete naturally)")

    try:
        logger.debug("[INTERRUPT] Calling state.client.interrupt()")
        await asyncio.wait_for(state.client.interrupt(), timeout=config.interrupt_timeout)
        logger.debug("[INTERRUPT] state.client.interrupt() returned successfully")

        logger.info(f"{reason}: interrupt sent")

        return True

    except TimeoutError:
        logger.debug("[INTERRUPT] Interrupt timed out; client likely still running")
        return False


def parse_assistant_message(msg: Message, *, state: vm.State) -> tuple[str | None, vm.State]:
    texts, new_context, session_id = vu.parse_assistant_message(msg, sub_agent_context=state.sub_agent_context)
    state.sub_agent_context = new_context
    if session_id:
        state.session_id = session_id
        logger.debug(f"[SESSION] Captured session_id: {session_id[:16]}...")
    return "\n".join(texts) if texts else None, state


async def converse(prompt: str, *, state: vm.State, config: vm.VestaConfig, show_output: bool) -> list[str]:
    assert state.client is not None
    client = state.client

    if state.pending_system_message:
        logger.debug("[CONVERSE] Injecting pending system message")
        prompt = f"{state.pending_system_message}\n\n{prompt}"
        state.pending_system_message = None

    timestamp = vfx.get_current_time()
    query_with_context = vu.build_query_with_timestamp(prompt, timestamp=timestamp)
    logger.debug(f"[CONVERSE] Sending query ({len(query_with_context)} chars)")
    await client.query(query_with_context)

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

    async def record(role: str, *, content: str) -> None:
        content = content.strip()
        if content:
            async with state.conversation_history_lock:
                state.conversation_history.append({"role": role, "content": content})

    await record("user", content=msg)

    responses = await converse(msg, state=state, config=config, show_output=is_user)
    logger.debug(f"Got {len(responses)} responses")
    if responses:
        await record("assistant", content="\n".join(responses))
    return responses, state


async def create_claude_client(config: vm.VestaConfig, *, state: vm.State, resume_session_id: str | None = None) -> ClaudeSDKClient:
    # Enable experimental MCP CLI features for skill hotloading
    os.environ["ENABLE_EXPERIMENTAL_MCP_CLI"] = "1"

    options = ClaudeAgentOptions(
        system_prompt=load_system_prompt(config),
        mcp_servers=build_mcp_servers(config),  # type: ignore[arg-type]
        hooks=build_hooks(state),
        permission_mode="bypassPermissions",
        resume=resume_session_id,
        cwd=config.state_dir,
        add_dirs=[str(config.state_dir), str(config.skills_dir), str(config.onedrive_dir)],
        max_thinking_tokens=config.max_thinking_tokens,
    )
    client = ClaudeSDKClient(options=options)
    await client.__aenter__()
    return client


async def reset_client_context(state: vm.State, *, config: vm.VestaConfig) -> None:
    """Close current client and create a new one with fresh memory."""
    logger.info("[CLIENT] Resetting client with updated memory...")

    state.client = None
    state.client = await create_claude_client(config, state=state)
    state.sub_agent_context = None
    state.session_id = None
    logger.info("[CLIENT] Client reset complete with fresh memory context")
