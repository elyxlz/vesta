import asyncio
import contextlib
import datetime as dt
import errno
import functools
import shutil
import signal
import threading
import traceback
import typing as tp

import aioconsole
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, HookMatcher, HookContext
from claude_agent_sdk.types import AgentDefinition, HookInput, HookJSONOutput, HookEvent

from vesta.playwright_tools import PLAYWRIGHT_TOOL_IDS

import vesta.memory_agent as vma
import vesta.models as vm
import vesta.utils as vu
import vesta.effects as vfx
import vesta.onedrive as vod
import vesta.logging_setup as vlog
from vesta.constants import Messages

logger = vfx.get_logger()


async def log_tool_start(input_data: HookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
    tool = input_data.get("tool_name", "unknown")  # type: ignore
    logger.info(f"TOOL start: {tool}")
    if tool == "Task":
        subagent = input_data.get("tool_input", {}).get("subagent_type")  # type: ignore
        if subagent:
            logger.info(f"SUBAGENT spawn: {subagent}")
    return {}


async def log_tool_finish(input_data: HookInput, tool_use_id: str | None, context: HookContext) -> HookJSONOutput:
    tool = input_data.get("tool_name", "unknown")  # type: ignore
    logger.info(f"TOOL done: {tool}")
    return {}


def build_hooks() -> dict[HookEvent, list[HookMatcher]]:
    return {
        "PreToolUse": [HookMatcher(hooks=[log_tool_start])],  # type: ignore
        "PostToolUse": [HookMatcher(hooks=[log_tool_finish])],  # type: ignore
    }


@contextlib.asynccontextmanager
async def heartbeat_logger(message_fn: tp.Callable[[], str], interval: float) -> tp.AsyncIterator[None]:
    async def pulse() -> None:
        while True:
            await asyncio.sleep(interval)
            logger.info(message_fn())

    task = asyncio.create_task(pulse())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def load_system_prompt(config: vm.VestaSettings) -> str:
    if not config.memory_file.exists():
        raise FileNotFoundError(f"MEMORY.md not found at {config.memory_file}")
    return config.memory_file.read_text()


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

    except Exception as e:
        if config.debug:
            logger.error(f"[INTERRUPT] Interrupt failed: {str(e)[:120]}")
            logger.debug(traceback.format_exc())
        return False


def parse_assistant_message(msg: tp.Any, *, state: vm.State, config: vm.VestaSettings) -> tuple[str | None, vm.State]:
    texts, new_context, session_id = vu.parse_assistant_message(msg, state.sub_agent_context)
    state.sub_agent_context = new_context
    if session_id:
        state.session_id = session_id
        logger.debug(f"[SESSION] Captured session_id: {session_id[:16]}...")
    return "\n".join(texts) if texts else None, state


async def load_notifications(*, config: vm.VestaSettings) -> list[vm.Notification]:
    file_contents = vfx.load_notification_files(config.notifications_dir)

    notifications = []
    for file, content in file_contents:
        if content:
            try:
                data = vu.parse_notification_file_content(content)
                notif = vm.Notification(**data)
                notif.file_path = str(file)
                if notif.message and notif.message.strip():
                    notifications.append(notif)
                else:
                    logger.info(f"Skipping media notification: {file.name}")
                    vfx.delete_file(file)  # Clean up file since it has no text content
            except Exception as e:
                logger.error(f"Failed to read notification {file.name}: {e}")

    return notifications


async def maybe_enqueue_whatsapp_greeting(queue: asyncio.Queue, *, config: vm.VestaSettings) -> None:
    if not config.enable_whatsapp_greeting:
        return

    servers = config.mcp_servers
    if "whatsapp" not in servers:
        return

    prompt = (config.whatsapp_greeting_prompt or "").strip()
    if not prompt:
        return

    await queue.put((prompt, False))
    logger.info("Queued WhatsApp greeting task")


async def delete_notification_files(notifications: list[vm.Notification]) -> None:
    paths = vu.extract_paths_to_delete(notifications)
    results = vfx.delete_files(paths)

    for path, success in results.items():
        if not success:
            logger.error(f"Failed to delete notification: {path}")


async def preserve_memory(state: vm.State, *, config: vm.VestaSettings) -> None:
    if config.ephemeral:
        logger.info("Skipping memory preservation (ephemeral mode)")
        return

    logger.info(f"Preserving memory (timeout {config.memory_agent_timeout}s)...")

    def log_progress(message: str) -> None:
        logger.info(f"Memory agent: {message}")

    start_time = dt.datetime.now()

    def heartbeat_message() -> str:
        elapsed = int((dt.datetime.now() - start_time).total_seconds())
        return f"Memory agent still running... {elapsed}s elapsed"

    async with heartbeat_logger(heartbeat_message, 30):
        try:
            async with state.conversation_history_lock:
                history = state.conversation_history.copy() if state.conversation_history else None

            diff = await vma.preserve_conversation_memory(history, config=config, progress_callback=log_progress)

            if diff:
                logger.info(Messages.MEMORY_UPDATED)
                logger.info(diff)
                async with state.conversation_history_lock:
                    state.conversation_history.clear()
            else:
                logger.info("Memory agent found no significant updates")
        except Exception as e:
            logger.error(f"Memory preservation failed: {e}")


async def output_line(text: str, state: vm.State, *, is_tool: bool = False) -> None:
    if not text or not text.strip():
        return
    if is_tool:
        logger.info(f"TOOL: {text}")
    else:
        logger.info(f"OUTPUT: {text}")


async def converse(prompt: str, *, state: vm.State, config: vm.VestaSettings, show_output: bool) -> list[str]:
    assert state.client is not None
    client = state.client

    timestamp = vfx.get_current_time()
    query_with_context = vu.build_query_with_timestamp(prompt, timestamp=timestamp)
    logger.debug(f"[CONVERSE] Sending query ({len(query_with_context)} chars)")
    await client.query(query_with_context)

    responses: list[str] = []

    async def collect() -> None:
        async for msg in client.receive_response():
            text, _ = parse_assistant_message(msg, state=state, config=config)
            if not text:
                continue
            lines = [line for line in text.split("\n") if line.strip()]
            if not show_output:
                responses.extend(lines)
                continue
            for line in lines:
                if line.startswith("[TOOL]") or line.startswith("[TASK]"):
                    await output_line(line, state, is_tool=True)
                else:
                    responses.append(line)

    try:
        await asyncio.wait_for(collect(), timeout=config.response_timeout)
    except asyncio.TimeoutError:
        responses.append("[Response timeout]")
        state.sub_agent_context = None
        await attempt_interrupt(state, config=config, reason="Response timeout")
    except Exception as e:
        logger.error(f"Response stream error: {type(e).__name__}: {str(e)[:200]}")
        if config.debug:
            logger.debug(traceback.format_exc())
        state.sub_agent_context = None
        await attempt_interrupt(state, config=config, reason="Response stream error")

    return responses


async def process_message(msg: str, state: vm.State, config: vm.VestaSettings, *, is_user: bool) -> tuple[list[str], vm.State]:
    logger.debug(f"Processing message (is_user={is_user})")

    async def record(role: str, content: str) -> None:
        content = content.strip()
        if content:
            async with state.conversation_history_lock:
                state.conversation_history.append({"role": role, "content": content})

    await record("user", msg)

    try:
        responses = await converse(msg, state=state, config=config, show_output=is_user)
        new_state = state
        logger.debug(f"Got {len(responses)} responses")
        if responses:
            await record("assistant", "\n".join(responses))
    except Exception as e:
        responses = [f"Error: {str(e)[:100]}"]
        logger.error(f"Message processing error: {e}")
        if config.debug:
            logger.debug(traceback.format_exc())
        new_state = state
    return responses, new_state


async def process_notification_batch(
    notifications: list[vm.Notification], queue: asyncio.Queue, state: vm.State, *, config: vm.VestaSettings
) -> None:
    if not notifications:
        return

    try:
        decision = vu.decide_notification_action(notifications, is_processing=state.is_processing, has_client=state.client is not None)
        prompt = vu.format_notification_batch(notifications)

        if decision == "interrupt" and state.client:
            logger.info(f"Interrupting task for {len(notifications)} notifications")
            success = await attempt_interrupt(state, config=config, reason="Notification interrupt")
            if not success:
                logger.warning("Could not interrupt current task; queued notification for later")
        if decision in {"queue", "interrupt"}:
            await queue.put((prompt, True))

        await delete_notification_files(notifications)
    except Exception as e:
        logger.error(f"Failed to process notification batch: {e}")
        logger.debug(traceback.format_exc())


def signal_handler(state: vm.State, config: vm.VestaSettings, signum: int, frame: tp.Any) -> None:
    state.shutdown_count += 1
    if state.shutdown_count == 1:
        if state.shutdown_event:
            state.shutdown_event.set()
    elif state.shutdown_count > 2:
        vfx.exit_process(0)


async def graceful_shutdown(state: vm.State, *, config: vm.VestaSettings) -> None:
    logger.info("=== Vesta shutting down ===")

    try:
        await asyncio.wait_for(preserve_memory(state, config=config), timeout=config.memory_agent_timeout)
    except asyncio.TimeoutError:
        logger.error("Memory preservation timeout")
    except Exception as e:
        logger.error(f"Memory error: {e}")

    if state.client:
        try:
            await state.client.__aexit__(None, None, None)
        except Exception as e:
            logger.warning(f"Error during client cleanup: {type(e).__name__}: {str(e)[:100]}")
            if config.debug:
                logger.debug(traceback.format_exc())

    if config.onedrive_dir.exists() and config.onedrive_token:
        try:
            vod.unmount_onedrive(config.onedrive_dir)
        except Exception as e:
            logger.error(f"Failed to unmount OneDrive: {e}")

    logger.info(Messages.SHUTDOWN_COMPLETE)


async def log_startup_info(config: vm.VestaSettings) -> None:
    logger.info("VESTA started")
    if config.mcp_servers:
        logger.info(f"Active MCPs: {', '.join(config.mcp_servers.keys())}")


def ensure_memory_file(config: vm.VestaSettings) -> None:
    if not config.memory_file.exists() and config.memory_template.exists():
        shutil.copy(config.memory_template, config.memory_file)
        logger.info("Created MEMORY.md from template")


async def message_processor(queue: asyncio.Queue, state: vm.State, *, config: vm.VestaSettings) -> None:
    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            msg, is_user = await asyncio.wait_for(queue.get(), timeout=1.0)
            logger.debug(f"Processing message (is_user={is_user}, length={len(msg)})")

            async with state.processing_lock:
                state.is_processing = True

            try:
                responses, _ = await process_message(msg, state, config, is_user=is_user)

                for response in responses:
                    if response and response.strip():
                        logger.info(f"ASSISTANT: {response}")
            finally:
                async with state.processing_lock:
                    state.is_processing = False

        except asyncio.TimeoutError:
            continue
        except Exception as e:
            logger.error(f"Queue error: {e}")
            logger.debug(traceback.format_exc())
            async with state.processing_lock:
                state.is_processing = False


async def input_handler(queue: asyncio.Queue, *, state: vm.State) -> None:
    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            user_msg = await aioconsole.ainput("> ")
            if state.shutdown_event and state.shutdown_event.is_set():
                break
            if not user_msg.strip():
                continue

            logger.info(f"USER: {user_msg.strip()}")
            await queue.put((user_msg.strip(), True))
        except (KeyboardInterrupt, EOFError):
            if state.shutdown_event:
                state.shutdown_event.set()
            break
        except asyncio.CancelledError:
            break
        except BlockingIOError:
            await asyncio.sleep(0.1)
            continue
        except OSError as e:
            if e.errno == errno.EAGAIN or e.errno == errno.EWOULDBLOCK:  # Resource temporarily unavailable
                await asyncio.sleep(0.1)
                continue
            else:
                raise


async def check_proactive_task(queue: asyncio.Queue, state: vm.State, *, config: vm.VestaSettings) -> None:
    logger.info(Messages.PROACTIVE_CHECK)
    await queue.put((config.proactive_check_message, False))


async def process_nightly_memory(queue: asyncio.Queue, state: vm.State, *, config: vm.VestaSettings) -> None:
    now = vfx.get_current_time()
    if config.enable_nightly_memory and now.hour == config.nightly_memory_time:
        if state.last_memory_consolidation is None or now.date() > state.last_memory_consolidation.date():
            logger.info(Messages.NIGHTLY_MEMORY)
            await preserve_memory(state, config=config)
            state.last_memory_consolidation = now
            logger.info("[MEMORY] Nightly memory consolidation completed successfully")
            if config.nightly_memory_completion_message:
                await queue.put((config.nightly_memory_completion_message, False))


async def load_and_display_new_notifications(
    notification_buffer: list[vm.Notification], *, buffer_start_time: dt.datetime | None, config: vm.VestaSettings
) -> tuple[list[vm.Notification], dt.datetime | None]:
    try:
        new_notifs = await load_notifications(config=config)

        if new_notifs:
            existing_paths = {n.file_path for n in notification_buffer if n.file_path}
            truly_new = vu.filter_new_notifications(new_notifs, existing_paths=existing_paths)

            if truly_new:
                notification_buffer.extend(truly_new)
                now = vfx.get_current_time()
                if buffer_start_time is None:
                    buffer_start_time = now

                for notif in truly_new:
                    sender = notif.sender or notif.source
                    msg_preview = notif.message[:200] + "..." if len(notif.message) > 200 else notif.message
                    logger.info(f"NOTIFICATION: {sender}: {msg_preview}")
    except Exception as e:
        logger.error(f"Error loading notifications: {e}")
        logger.debug(traceback.format_exc())

    return notification_buffer, buffer_start_time


async def monitor_loop(queue: asyncio.Queue, state: vm.State, *, config: vm.VestaSettings) -> None:
    last_proactive = vfx.get_current_time()
    notification_buffer = []
    buffer_start_time = None

    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            await asyncio.sleep(config.notification_check_interval)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Monitor loop sleep error: {e}")
            continue

        if state.shutdown_event and state.shutdown_event.is_set():
            break

        try:
            now = vfx.get_current_time()

            if (now - last_proactive).total_seconds() >= config.proactive_check_interval * 60:
                await check_proactive_task(queue, state, config=config)
                last_proactive = now

            await process_nightly_memory(queue, state, config=config)

            notification_buffer, buffer_start_time = await load_and_display_new_notifications(
                notification_buffer, buffer_start_time=buffer_start_time, config=config
            )

            if vu.should_process_notification_buffer(
                notification_buffer, buffer_start_time, now, buffer_delay=config.notification_buffer_delay
            ):
                try:
                    await process_notification_batch(notification_buffer, queue, state, config=config)
                    notification_buffer = []
                    buffer_start_time = None
                except Exception as e:
                    logger.error(f"Error processing notifications: {e}")
                    logger.debug(traceback.format_exc())
                    notification_buffer = []
                    buffer_start_time = None

        except Exception as e:
            logger.error(f"CRITICAL: Monitor loop iteration crashed: {e}")
            logger.debug(traceback.format_exc())
            continue


async def run_vesta(config: vm.VestaSettings, *, state: vm.State) -> None:
    state.shutdown_event = asyncio.Event()

    handler = functools.partial(signal_handler, state, config)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    await log_startup_info(config)

    message_queue = asyncio.Queue()

    tasks = [
        asyncio.create_task(input_handler(message_queue, state=state)),
        asyncio.create_task(message_processor(message_queue, state, config=config)),
        asyncio.create_task(monitor_loop(message_queue, state, config=config)),
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


async def create_claude_client(config: vm.VestaSettings, resume_session_id: str | None = None) -> ClaudeSDKClient:
    options = ClaudeAgentOptions(
        system_prompt=load_system_prompt(config),
        mcp_servers=config.mcp_servers,  # type: ignore
        hooks=build_hooks(),
        permission_mode="bypassPermissions",
        model="sonnet",
        resume=resume_session_id,
        cwd=config.state_dir,
        add_dirs=[config.state_dir],
        disallowed_tools=PLAYWRIGHT_TOOL_IDS,
        agents={
            "browser": AgentDefinition(
                description="Use this agent when you need to browse the web with Playwright for screenshots or scraping.",
                prompt="You are a browser specialist. Only use the Playwright MCP tools. Do not use other tools.",
                tools=PLAYWRIGHT_TOOL_IDS,
                model="haiku",
            )
        },
    )
    client = ClaudeSDKClient(options=options)
    await client.__aenter__()
    return client


async def init_state(*, config: vm.VestaSettings) -> vm.State:
    client = await create_claude_client(config)

    now = vfx.get_current_time()
    return vm.State(
        client=client,
        shutdown_event=None,
        shutdown_lock=threading.Lock(),
        shutdown_count=0,
        is_processing=False,
        sub_agent_context=None,
        session_id=None,
        last_memory_consolidation=now,
    )


async def async_main() -> None:
    config = vm.VestaSettings()
    logger.info(f"Config: {config.model_dump()}")

    for path in [config.state_dir, config.notifications_dir, config.logs_dir, config.data_dir, config.onedrive_dir]:
        path.mkdir(parents=True, exist_ok=True)

    ensure_memory_file(config)

    vlog.setup_logging(config.logs_dir, debug=config.debug)
    logger.info("=== Vesta starting ===")

    if config.onedrive_token:
        logger.info("Setting up OneDrive mount...")
        vod.unmount_onedrive(config.onedrive_dir)
        vod.setup_rclone_config(config, config_path=config.rclone_config_file)
        await vod.mount_onedrive(config, config.onedrive_dir, config.rclone_config_file)
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
