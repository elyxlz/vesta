import asyncio
import contextlib
import shutil
import signal

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, Message

from vesta.registry import build_all_agents, generate_delegation_prompt, build_mcp_servers
from vesta.memory import load_memory, preserve_memory
from vesta.hooks import build_hooks
import vesta.models as vm
import vesta.utils as vu
import vesta.effects as vfx
from vesta.effects import logger
import vesta.onedrive as vod
import vesta.logging_setup as vlog
from vesta.constants import Messages
from vesta.signals import make_signal_handler
from vesta.io_handler import input_handler, output_line
from vesta.notifications import (
    load_and_display_new_notifications,
    maybe_enqueue_whatsapp_greeting,
    delete_notification_files,
)


def load_system_prompt(config: vm.VestaSettings) -> str:
    """Load main agent's memory as system prompt with delegation instructions."""
    memory = load_memory(config, agent_name="main")
    return f"{memory}\n\n{generate_delegation_prompt(config)}"


async def attempt_interrupt(state: vm.State, *, config: vm.VestaSettings, reason: str) -> bool:
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

    except asyncio.TimeoutError:
        logger.debug("[INTERRUPT] Interrupt timed out; client likely still running")
        return False


def parse_assistant_message(msg: Message, *, state: vm.State) -> tuple[str | None, vm.State]:
    texts, new_context, session_id = vu.parse_assistant_message(msg, sub_agent_context=state.sub_agent_context)
    state.sub_agent_context = new_context
    if session_id:
        state.session_id = session_id
        logger.debug(f"[SESSION] Captured session_id: {session_id[:16]}...")
    return "\n".join(texts) if texts else None, state


async def converse(prompt: str, *, state: vm.State, config: vm.VestaSettings, show_output: bool) -> list[str]:
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
    except asyncio.TimeoutError:
        responses.append("[Response timeout]")
        state.sub_agent_context = None
        await attempt_interrupt(state, config=config, reason="Response timeout")

    return responses


async def process_message(msg: str, *, state: vm.State, config: vm.VestaSettings, is_user: bool) -> tuple[list[str], vm.State]:
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


async def process_notification_batch(
    notifications: list[vm.Notification], *, queue: asyncio.Queue, state: vm.State, config: vm.VestaSettings
) -> None:
    if not notifications:
        return

    async with state.processing_lock:
        is_processing = state.is_processing
        has_client = state.client is not None
    decision = vu.decide_notification_action(notifications, is_processing=is_processing, has_client=has_client)
    prompt = vu.format_notification_batch(notifications, suffix=config.notification_suffix)

    if decision == "interrupt" and state.client:
        logger.info(f"Interrupting task for {len(notifications)} notifications")
        success = await attempt_interrupt(state, config=config, reason="Notification interrupt")
        if not success:
            logger.warning("Could not interrupt current task; queued notification for later")
    if decision in {"queue", "interrupt"}:
        await queue.put((prompt, True))

    await delete_notification_files(notifications)


async def graceful_shutdown(state: vm.State, *, config: vm.VestaSettings) -> None:
    logger.info("=== Vesta shutting down ===")

    await asyncio.wait_for(preserve_memory(state, config=config), timeout=config.memory_agent_timeout)

    if state.client:
        await state.client.__aexit__(None, None, None)

    if config.onedrive_dir.exists() and config.onedrive_token:
        vod.unmount_onedrive(config.onedrive_dir)

    logger.info(Messages.SHUTDOWN_COMPLETE)


async def log_startup_info(config: vm.VestaSettings) -> None:
    logger.info("VESTA started")
    mcps = build_mcp_servers(config)
    if mcps:
        logger.info(f"Active MCPs: {', '.join(mcps.keys())}")


async def message_processor(queue: asyncio.Queue, *, state: vm.State, config: vm.VestaSettings) -> None:
    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            msg, is_user = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        logger.debug(f"Processing message (is_user={is_user}, length={len(msg)})")

        async with state.processing_lock:
            state.is_processing = True

        try:
            responses, _ = await process_message(msg, state=state, config=config, is_user=is_user)

            for response in responses:
                if response and response.strip():
                    logger.info(f"ASSISTANT: {response}")
        finally:
            async with state.processing_lock:
                state.is_processing = False


async def check_proactive_task(queue: asyncio.Queue, *, config: vm.VestaSettings) -> None:
    logger.info(Messages.PROACTIVE_CHECK)
    await queue.put((config.proactive_check_message, False))


async def process_nightly_memory(state: vm.State, *, config: vm.VestaSettings) -> None:
    now = vfx.get_current_time()
    if config.nightly_memory_hour is not None and now.hour == config.nightly_memory_hour:
        if state.last_memory_consolidation is None or now.date() > state.last_memory_consolidation.date():
            logger.info(Messages.NIGHTLY_MEMORY)
            updated = await preserve_memory(state, config=config)
            state.last_memory_consolidation = now
            logger.info("[MEMORY] Nightly memory consolidation completed successfully")
            if updated:
                await reset_client_context(state, config=config)
            if config.nightly_memory_completion_message:
                state.pending_system_message = config.nightly_memory_completion_message


async def monitor_loop(queue: asyncio.Queue, *, state: vm.State, config: vm.VestaSettings) -> None:
    last_proactive = vfx.get_current_time()
    notification_buffer: list[vm.Notification] = []
    buffer_start_time = None

    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            await asyncio.sleep(config.notification_check_interval)

            if state.shutdown_event and state.shutdown_event.is_set():
                break

            now = vfx.get_current_time()

            if (now - last_proactive).total_seconds() >= config.proactive_check_interval * 60:
                await check_proactive_task(queue, config=config)
                last_proactive = now

            await process_nightly_memory(state, config=config)

            notification_buffer, buffer_start_time = await load_and_display_new_notifications(
                notification_buffer, buffer_start_time=buffer_start_time, config=config
            )

            if vu.should_process_notification_buffer(
                notification_buffer, buffer_start_time=buffer_start_time, current_time=now, buffer_delay=config.notification_buffer_delay
            ):
                await process_notification_batch(notification_buffer, queue=queue, state=state, config=config)
                notification_buffer = []
                buffer_start_time = None
        except asyncio.CancelledError:
            break


async def run_vesta(config: vm.VestaSettings, *, state: vm.State) -> None:
    state.shutdown_event = asyncio.Event()

    handler = make_signal_handler(state)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    await log_startup_info(config)

    message_queue = asyncio.Queue()

    tasks = [
        asyncio.create_task(input_handler(message_queue, state=state)),
        asyncio.create_task(message_processor(message_queue, state=state, config=config)),
        asyncio.create_task(monitor_loop(message_queue, state=state, config=config)),
    ]

    await maybe_enqueue_whatsapp_greeting(message_queue, config=config)

    try:
        if state.shutdown_event:
            await state.shutdown_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        if state.shutdown_event:
            state.shutdown_event.set()

    logger.info(Messages.SHUTDOWN_INITIATED)

    for task in tasks:
        task.cancel()

    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=config.task_gather_timeout,
        )
    except asyncio.TimeoutError:
        pass

    try:
        await asyncio.wait_for(graceful_shutdown(state, config=config), timeout=config.shutdown_timeout)
    except asyncio.TimeoutError:
        logger.error("Shutdown timeout")


def check_dependencies() -> None:
    if shutil.which("npm") is None:
        raise RuntimeError("npm is not found in PATH. Please install Node.js and npm: https://nodejs.org/")

    if shutil.which("node") is None:
        raise RuntimeError("node is not found in PATH. Please install Node.js: https://nodejs.org/")

    if shutil.which("uv") is None:
        raise RuntimeError("uv is not found in PATH. Please install uv: https://docs.astral.sh/uv/getting-started/installation/")

    if shutil.which("go") is None:
        raise RuntimeError("go is not found in PATH. Please install Go: https://go.dev/doc/install")

    if not vod.check_rclone_installed():
        raise RuntimeError("rclone is not found in PATH. Please install rclone: https://rclone.org/install/")


async def create_claude_client(config: vm.VestaSettings, *, state: vm.State, resume_session_id: str | None = None) -> ClaudeSDKClient:
    options = ClaudeAgentOptions(
        system_prompt=load_system_prompt(config),
        mcp_servers=build_mcp_servers(config),  # type: ignore[arg-type]
        hooks=build_hooks(state),
        permission_mode="bypassPermissions",
        resume=resume_session_id,
        cwd=config.state_dir,
        add_dirs=[config.state_dir],
        max_thinking_tokens=config.max_thinking_tokens,
        agents=build_all_agents(config),
    )
    client = ClaudeSDKClient(options=options)
    await client.__aenter__()
    return client


async def reset_client_context(state: vm.State, *, config: vm.VestaSettings) -> None:
    """Close current client and create a new one with fresh memory."""
    logger.info("[CLIENT] Resetting client with updated memory...")

    old_client = state.client
    state.client = None  # Clear reference first

    # Close old client in a separate task to avoid cancel scope propagation
    # (Claude SDK uses anyio internally; closing the client cancels scopes
    # that would otherwise propagate CancelledError to the caller)
    if old_client:

        async def close_old_client() -> None:
            try:
                await old_client.__aexit__(None, None, None)
            except asyncio.CancelledError:
                logger.debug("[CLIENT] Old client close cancelled (expected)")
            except Exception as e:
                logger.warning(f"[CLIENT] Error closing old client: {e}")

        close_task = asyncio.create_task(close_old_client())
        try:
            await asyncio.wait_for(close_task, timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("[CLIENT] Old client close timed out")
            close_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await close_task

    state.client = await create_claude_client(config, state=state)
    state.sub_agent_context = None
    state.session_id = None
    logger.info("[CLIENT] Client reset complete with fresh memory context")


async def init_state(*, config: vm.VestaSettings) -> vm.State:
    now = vfx.get_current_time()
    state = vm.State(
        client=None,
        shutdown_event=None,
        shutdown_count=0,
        is_processing=False,
        sub_agent_context=None,
        session_id=None,
        pending_system_message=None,
        last_memory_consolidation=now,
    )
    state.client = await create_claude_client(config, state=state)
    return state


async def async_main() -> None:
    config = vm.VestaSettings()
    logger.info(f"Config: {config.model_dump(mode='json')}")

    for path in [config.state_dir, config.notifications_dir, config.logs_dir, config.data_dir]:
        path.mkdir(parents=True, exist_ok=True)

    vlog.setup_logging(config.logs_dir, debug=config.debug)
    logger.info("=== Vesta starting ===")

    if config.onedrive_token:
        logger.info("Setting up OneDrive mount...")
        vod.unmount_onedrive(config.onedrive_dir)
        vod.setup_rclone_config(config, config_path=config.rclone_config_file)
        await vod.mount_onedrive(config, mount_dir=config.onedrive_dir, config_path=config.rclone_config_file)
        logger.info(f"OneDrive mounted at {config.onedrive_dir}")

    initial_state = await init_state(config=config)

    await run_vesta(config, state=initial_state)


def main() -> None:
    check_dependencies()

    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.critical("Fatal error", exc_info=True)


if __name__ == "__main__":
    main()
