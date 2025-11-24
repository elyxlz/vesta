import asyncio
import contextlib
import datetime as dt
import errno
import functools
import os
import shutil
import signal
import threading
import traceback
import typing as tp

import aioconsole
import claude_code_sdk as ccsdk
import claude_code_sdk.types as ccsdk_types

import vesta.memory_agent as vma
import vesta.models as vm
import vesta.utils as vu
import vesta.effects as vfx
import vesta.onedrive as vod
import vesta.logging_setup as vlog
from vesta.constants import Messages

logger = vfx.get_logger()


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

    subprocess_pid = None
    try:
        if hasattr(state.client, "_transport") and state.client._transport:
            if hasattr(state.client._transport, "_process") and state.client._transport._process:
                subprocess_pid = state.client._transport._process.pid
    except Exception:
        pass

    try:
        logger.debug("[INTERRUPT] Calling state.client.interrupt()")
        await asyncio.wait_for(state.client.interrupt(), timeout=config.interrupt_timeout)
        logger.debug("[INTERRUPT] state.client.interrupt() returned successfully")

        logger.debug("[INTERRUPT] Nulling client to force restart (client broken after interrupt)")
        state.client = None

        logger.info(f"{reason}: interrupt sent")

        return True

    except asyncio.TimeoutError:
        logger.debug("[INTERRUPT] Interrupt timed out, forcing client restart")

        if subprocess_pid:
            try:
                os.kill(subprocess_pid, signal.SIGKILL)
                logger.debug(f"[INTERRUPT] Force-killed subprocess {subprocess_pid}")
            except (ProcessLookupError, Exception):
                pass

        state.client = None  # Only null client on timeout
        return False

    except Exception as e:
        if config.debug:
            logger.error(f"[INTERRUPT] Interrupt failed: {str(e)[:120]}")
            logger.debug(traceback.format_exc())
        return False


async def settle_collect_task(task: "asyncio.Task[tp.Any]", *, timeout: float, config: vm.VestaSettings) -> None:
    logger.debug(f"[SETTLE] Starting (task.done()={task.done()})")

    if task.done():
        logger.debug("[SETTLE] Task already done, returning")
        return

    try:
        logger.debug("[SETTLE] Waiting for task to complete")
        await asyncio.wait_for(task, timeout=timeout)
        logger.debug("[SETTLE] Task completed successfully")
    except asyncio.TimeoutError:
        logger.debug("[SETTLE] Task timed out, cancelling")
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=timeout)
        logger.debug("[SETTLE] Task cancelled or abandoned")
    except BaseException as e:
        logger.debug(f"[SETTLE] Exception: {type(e).__name__}")

    logger.debug("[SETTLE] Completed")


async def ensure_client_ready(state: vm.State, *, config: vm.VestaSettings, context: str = "restart") -> tuple[bool, str | None]:
    if state.restart_lock.locked():
        logger.debug(f"[{context.upper()}] Restart already in progress (lock held)")
        await asyncio.sleep(1.0)
        if not state.client:
            return False, "[Waiting for restart to complete...]"
        return True, None

    logger.debug(f"[{context.upper()}] Attempting to acquire restart_lock")
    try:
        async with asyncio.timeout(config.restart_timeout + 5):
            async with state.restart_lock:
                logger.debug(f"[{context.upper()}] restart_lock acquired")
                try:
                    await asyncio.wait_for(restart_claude_session(state, config=config), timeout=config.restart_timeout)
                    if state.client:
                        logger.debug(f"[{context.upper()}] Client restarted successfully")
                        state.pending_system_message = "System: You timed out and were restarted. You may continue with the user's request."
                        return True, None
                    else:
                        return False, "[Error: Client restart failed - client is None after restart]"
                except asyncio.TimeoutError:
                    state.client = None
                    return False, f"[Error: Client restart timed out after {config.restart_timeout}s]"
                except Exception as e:
                    state.client = None
                    return False, f"[Error: Client restart failed - {str(e)[:50]}]"
    except asyncio.TimeoutError:
        state.client = None
        return False, "[Error: Failed to acquire restart lock - deadlock detected]"


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

    async def heartbeat() -> None:
        try:
            while True:
                await asyncio.sleep(30)
                elapsed = int((dt.datetime.now() - start_time).total_seconds())
                logger.info(f"Memory agent still running... {elapsed}s elapsed")
        except asyncio.CancelledError:
            pass

    heartbeat_task = asyncio.create_task(heartbeat())

    try:
        diff = await vma.preserve_conversation_memory(None, config=config, progress_callback=log_progress)
        if diff:
            logger.info(Messages.MEMORY_UPDATED)
            logger.info(diff)
        else:
            logger.info("Memory agent found no significant updates")
    except Exception as e:
        logger.error(f"Memory preservation failed: {e}")
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task


async def output_line(text: str, state: vm.State, *, is_tool: bool = False) -> None:
    if not text or not text.strip():
        return
    if is_tool:
        logger.info(f"TOOL: {text}")
    else:
        logger.info(f"OUTPUT: {text}")


async def send_query(client: ccsdk.ClaudeSDKClient, prompt: str, state: vm.State, *, config: vm.VestaSettings) -> vm.State:
    logger.debug("[QUERY] Starting send_query")
    logger.debug(f"[QUERY] Client exists: {client is not None}")
    logger.debug(f"[QUERY] State.client exists: {state.client is not None}")

    if state.pending_system_message:
        logger.debug("[QUERY] Injecting pending system message")
        prompt = f"{state.pending_system_message}\n\n{prompt}"
        state.pending_system_message = None  # Clear after using

    timestamp = vfx.get_current_time()
    query_with_context = vu.build_query_with_timestamp(prompt, timestamp=timestamp)

    logger.debug(f"[QUERY] Calling client.query() with {len(query_with_context)} chars")
    await client.query(query_with_context)
    logger.debug("[QUERY] client.query() returned successfully")

    return state


async def collect_responses(
    client: ccsdk.ClaudeSDKClient, *, state: vm.State, config: vm.VestaSettings, show_output: bool = True
) -> tuple[list[str], vm.State]:
    logger.debug("[COLLECT] Starting collect_responses")
    responses = []
    should_restart_client = False

    async def collect():
        logger.debug("[COLLECT] Starting receive_response loop")
        try:
            async for msg in client.receive_response():
                logger.debug(f"[COLLECT] Received message: {type(msg).__name__}")
                text, _ = parse_assistant_message(msg, state=state, config=config)

                if text:
                    if show_output:
                        for line in text.split("\n"):
                            if line.strip():
                                if line.startswith("[TOOL]") or line.startswith("[TASK]"):
                                    await output_line(line, state, is_tool=True)
                                else:
                                    responses.append(line)
            logger.debug("[COLLECT] receive_response loop completed normally")
        except asyncio.CancelledError:
            logger.debug("[COLLECT] receive_response loop caught CancelledError")
            raise
        except Exception as e:
            if config.debug:
                logger.error(f"[COLLECT] receive_response loop error: {type(e).__name__}: {e}")
            raise

    logger.debug("[COLLECT] Creating collect task")
    collect_task = asyncio.create_task(collect())

    try:
        logger.debug("[COLLECT] Waiting for collect task")
        await asyncio.wait_for(collect_task, timeout=config.response_timeout)
        logger.debug("[COLLECT] collect task completed successfully")
    except asyncio.TimeoutError:
        logger.debug("[COLLECT] collect task timed out")
        responses.append("[Response timeout]")
        state.sub_agent_context = None
        await attempt_interrupt(state, config=config, reason="Response timeout")
        collect_task.cancel()
        should_restart_client = True
    except Exception:
        state.sub_agent_context = None
        await attempt_interrupt(state, config=config, reason="Response stream error")
        should_restart_client = True
    finally:
        logger.debug("[COLLECT] Entering finally block")
        await settle_collect_task(collect_task, timeout=config.interrupt_timeout, config=config)
        logger.debug("[COLLECT] settle_collect_task returned")

    if should_restart_client:
        logger.debug("[COLLECT] Client needs restart")
        success, error_msg = await ensure_client_ready(state, config=config, context="collect")
        if not success and error_msg:
            responses.append(error_msg)
            if "timed out" in error_msg or "deadlock" in error_msg:
                logger.error(error_msg.strip("[]"))

    return responses, state


async def send_and_receive_message(
    prompt: str, *, state: vm.State, config: vm.VestaSettings, show_in_chat: bool = True
) -> tuple[list[str], vm.State]:
    logger.debug("[SEND-RECV] Starting send_and_receive_message")
    logger.debug(f"[SEND-RECV] Client state: {state.client is not None}")

    if not state.client:
        logger.debug("[SEND-RECV] Client is None, attempting automatic recovery...")
        success, error_msg = await ensure_client_ready(state, config=config, context="send-recv")
        if not success:
            if error_msg:
                logger.error(error_msg.strip("[]"))
                return [error_msg], state
            return ["[Error: Client recovery failed]"], state
        logger.info("Client recovered successfully")

    assert state.client is not None  # Guaranteed by recovery above
    logger.debug("[SEND-RECV] Calling send_query")
    try:
        await send_query(state.client, prompt, state, config=config)
        logger.debug("[SEND-RECV] send_query completed successfully")
    except Exception as e:
        error_msg = f"failed to send message: {str(e)[:100]}"
        if config.debug:
            logger.error(f"[SEND-RECV] send_query failed: {error_msg}")
            logger.debug(traceback.format_exc())
        return [error_msg], state

    logger.debug("[SEND-RECV] Calling collect_responses")
    responses, _ = await collect_responses(state.client, state=state, config=config, show_output=show_in_chat)
    logger.debug(f"[SEND-RECV] collect_responses returned {len(responses)} responses")

    return responses, state


async def process_message(msg: str, state: vm.State, config: vm.VestaSettings, *, is_user: bool) -> tuple[list[str], vm.State]:
    logger.debug(f"Processing message (is_user={is_user})")

    try:
        responses, new_state = await send_and_receive_message(msg, state=state, config=config, show_in_chat=is_user)
        logger.debug(f"Got {len(responses)} responses")
    except Exception as e:
        responses = [f"Error: {str(e)[:100]}"]
        logger.error(f"Message processing error: {e}")
        new_state = state

    return responses, new_state


async def handle_notifications_interrupt(
    notifications: list[vm.Notification], queue: asyncio.Queue, state: vm.State, config: vm.VestaSettings
) -> None:
    logger.info(f"Interrupting task for {len(notifications)} notifications")

    prompt = vu.format_notification_batch(notifications)
    success = await attempt_interrupt(state, config=config, reason="Notification interrupt")

    if not success:
        logger.warning("Could not interrupt current task; queued notification for later")
    else:
        logger.info("Interrupt succeeded")

    logger.debug(f"[NOTIF-INT] Queuing notification prompt (length: {len(prompt)} chars)")
    await queue.put((prompt, True))
    logger.debug("[NOTIF-INT] Notification queued, exiting handle_notifications_interrupt")


async def process_notification_batch(
    notifications: list[vm.Notification], queue: asyncio.Queue, state: vm.State, *, config: vm.VestaSettings
) -> None:
    if not notifications:
        return

    try:
        decision = vu.decide_notification_action(notifications, is_processing=state.is_processing, has_client=state.client is not None)

        if decision == "interrupt" and state.client:
            await handle_notifications_interrupt(notifications, queue, state, config)
        elif decision == "queue":
            prompt = vu.format_notification_batch(notifications)
            await queue.put((prompt, True))

        await delete_notification_files(notifications)
    except Exception as e:
        logger.error(f"Failed to process notification batch: {e}")
        logger.debug(traceback.format_exc())


def signal_handler(state: vm.State, config: vm.VestaSettings, signum: int, frame: tp.Any) -> None:
    with state.shutdown_lock:
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
        except Exception:
            pass

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


async def process_nightly_memory(state: vm.State, *, config: vm.VestaSettings) -> None:
    now = vfx.get_current_time()
    if config.enable_nightly_memory and now.hour >= config.nightly_memory_time:
        if state.last_memory_consolidation is None or now.date() > state.last_memory_consolidation.date():
            logger.info(Messages.NIGHTLY_MEMORY)
            await preserve_memory(state, config=config)
            state.last_memory_consolidation = now


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

            await process_nightly_memory(state, config=config)

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

    ensure_memory_file(config)
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

    if shutil.which("uv") is None:
        raise RuntimeError("uv is not found in PATH. Please install uv: https://docs.astral.sh/uv/getting-started/installation/")

    if not vod.check_rclone_installed():
        raise RuntimeError("rclone is not found in PATH. Please install rclone: https://rclone.org/install/")


async def create_claude_client(config: vm.VestaSettings, resume_session_id: str | None = None) -> ccsdk.ClaudeSDKClient:
    client = ccsdk.ClaudeSDKClient(
        options=ccsdk.ClaudeCodeOptions(
            system_prompt=load_system_prompt(config),
            mcp_servers=tp.cast(dict[str, ccsdk_types.McpServerConfig], config.mcp_servers),
            hooks={},
            permission_mode="bypassPermissions",
            model="sonnet",
            resume=resume_session_id,
        )
    )
    await asyncio.wait_for(client.__aenter__(), timeout=config.restart_timeout)
    return client


async def restart_claude_session(state: vm.State, *, config: vm.VestaSettings) -> None:
    if state.shutdown_event and state.shutdown_event.is_set():
        logger.info("Skipping restart - shutdown in progress")
        return

    old_process_pid = None
    if state.client:
        try:
            if hasattr(state.client, "_transport") and state.client._transport:
                if hasattr(state.client._transport, "_process") and state.client._transport._process:
                    old_process_pid = state.client._transport._process.pid
        except Exception:
            pass  # Best effort

        try:
            await asyncio.wait_for(state.client.__aexit__(None, None, None), timeout=config.interrupt_timeout)
        except asyncio.TimeoutError:
            logger.error(f"Client exit timed out after {config.interrupt_timeout}s")
            if old_process_pid:
                try:
                    os.kill(old_process_pid, signal.SIGKILL)
                    logger.info(f"Force killed subprocess {old_process_pid}")
                except ProcessLookupError:
                    pass  # Process already dead
                except Exception as e:
                    logger.error(f"Failed to kill subprocess: {e}")
        except Exception as e:
            logger.error(f"Error while closing Claude client: {e}")
        finally:
            state.client = None

    try:
        state.client = await create_claude_client(config, resume_session_id=state.session_id)
        state.sub_agent_context = None
        logger.info(f"Restarted client{' (resuming session ' + state.session_id + ')' if state.session_id else ''}")
    except Exception as e:
        logger.error(f"Failed to recreate Claude client: {e}")


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
        pending_system_message=None,
        last_memory_consolidation=now,
    )


async def async_main() -> None:
    config = vm.VestaSettings()

    vlog.setup_logging(config.logs_dir, debug=config.debug)
    logger.info("=== Vesta starting ===")

    if config.onedrive_token:
        try:
            logger.info("Setting up OneDrive mount...")
            vod.setup_rclone_config(config, config_path=config.rclone_config_file)
            await vod.mount_onedrive(config, config.onedrive_dir, config.rclone_config_file)
            logger.info(f"OneDrive mounted at {config.onedrive_dir}")
        except Exception as e:
            raise RuntimeError(f"Failed to mount OneDrive: {e}") from e

    initial_state = await init_state(config=config)

    await run_vesta(config, state=initial_state)


def main() -> None:
    check_dependencies()

    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        logger.debug(traceback.format_exc())


if __name__ == "__main__":
    main()
