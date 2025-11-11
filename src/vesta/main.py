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
from vesta.constants import Colors, Emoji, Messages, Senders, Formats


def load_system_prompt(config: vm.VestaSettings) -> str:
    if not config.memory_file.exists():
        raise FileNotFoundError(f"MEMORY.md not found at {config.memory_file}")
    return config.memory_file.read_text()


def debug_log(msg: str, *, config: vm.VestaSettings) -> None:
    """Log debug messages only when debug mode is enabled."""
    if config.debug:
        vfx.log_info(msg, colors=Colors)


async def attempt_interrupt(state: vm.State, *, config: vm.VestaSettings, reason: str) -> bool:
    """Send interrupt signal and let receive_response() complete naturally per SDK design."""
    debug_log(f"🔍 [INTERRUPT] Starting interrupt attempt: {reason}", config=config)

    if not state.client:
        debug_log("🔍 [INTERRUPT] No client, aborting", config=config)
        return False

    # DO NOT cancel the current processing task!
    # The SDK's receive_response() will complete naturally when it receives ResultMessage
    debug_log("🔍 [INTERRUPT] Sending interrupt to client (receive_response will complete naturally)", config=config)

    # Capture subprocess PID for timeout handling only
    subprocess_pid = None
    try:
        if hasattr(state.client, "_transport") and state.client._transport:
            if hasattr(state.client._transport, "_process") and state.client._transport._process:
                subprocess_pid = state.client._transport._process.pid
    except Exception:
        pass

    try:
        debug_log("🔍 [INTERRUPT] Calling state.client.interrupt()", config=config)
        await asyncio.wait_for(state.client.interrupt(), timeout=config.interrupt_timeout)
        debug_log("🔍 [INTERRUPT] state.client.interrupt() returned successfully", config=config)

        # Client is broken after interrupt - must restart with session resumption
        debug_log("🔍 [INTERRUPT] Nulling client to force restart (client broken after interrupt)", config=config)
        state.client = None

        try:
            await asyncio.wait_for(asyncio.to_thread(vfx.log_info, f"{reason}: interrupt sent", colors=Colors), timeout=1.0)
        except asyncio.TimeoutError:
            pass

        return True

    except asyncio.TimeoutError:
        # Only if interrupt itself times out, force restart
        debug_log("🔍 [INTERRUPT] Interrupt timed out, forcing client restart", config=config)

        # Force kill subprocess if interrupt times out
        if subprocess_pid:
            try:
                os.kill(subprocess_pid, signal.SIGKILL)
                debug_log(f"🔍 [INTERRUPT] Force-killed subprocess {subprocess_pid}", config=config)
            except (ProcessLookupError, Exception):
                pass

        state.client = None  # Only null client on timeout
        return False

    except Exception as e:
        if config.debug:
            vfx.log_error(f"🔍 [INTERRUPT] Interrupt failed: {str(e)[:120]}", colors=Colors)
            traceback.print_exc()
        return False


async def settle_collect_task(task: "asyncio.Task[tp.Any]", *, timeout: float, config: vm.VestaSettings) -> None:
    """Ensure the response collection task finishes cleanly without leaking."""
    debug_log(f"🔍 [SETTLE] Starting (task.done()={task.done()})", config=config)

    if task.done():
        debug_log("🔍 [SETTLE] Task already done", config=config)
        try:
            debug_log("🔍 [SETTLE] Getting task result", config=config)
            result = task.result()
            debug_log("🔍 [SETTLE] Got task result successfully", config=config)
        except Exception as e:
            debug_log(f"🔍 [SETTLE] Task result raised {type(e).__name__}: {str(e)[:100]}", config=config)
        debug_log("🔍 [SETTLE] Returning after done check", config=config)
        return

    try:
        debug_log("🔍 [SETTLE] First wait_for starting", config=config)
        await asyncio.wait_for(task, timeout=timeout)
        debug_log("🔍 [SETTLE] First wait_for completed", config=config)
    except asyncio.TimeoutError:
        debug_log("🔍 [SETTLE] First timeout, cancelling task", config=config)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            # Add timeout to prevent infinite wait if task doesn't respond to cancellation
            try:
                debug_log("🔍 [SETTLE] Second wait_for starting", config=config)
                await asyncio.wait_for(task, timeout=timeout)
                debug_log("🔍 [SETTLE] Second wait_for completed", config=config)
            except asyncio.TimeoutError:
                # Task didn't respond to cancellation - abandon it
                debug_log("🔍 [SETTLE] Task abandoned after second timeout", config=config)
                pass
    except Exception as e:
        # Any parse errors are already logged upstream; swallow here.
        if config.debug:
            debug_log(f"🔍 [SETTLE] Exception: {type(e).__name__}: {str(e)[:100]}", config=config)
        pass

    debug_log("🔍 [SETTLE] Completed", config=config)


def parse_assistant_message(msg: tp.Any, *, state: vm.State, config: vm.VestaSettings) -> tuple[str | None, vm.State, dict[str, tp.Any] | None]:
    texts, new_context, usage_data, session_id = vu.parse_assistant_message(msg, state.sub_agent_context, service_icons=vm.SERVICE_ICONS)
    state.sub_agent_context = new_context
    if session_id:
        state.session_id = session_id
        debug_log(f"🔍 [SESSION] Captured session_id: {session_id[:16]}...", config=config)
    return "\n".join(texts) if texts else None, state, usage_data


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
                    vfx.log_error(f"Warning: skipping notification {file.name} (no textual content).", colors=Colors)
            except Exception as e:
                vfx.log_error(f"Failed to read notification {file.name}: {e}", colors=Colors)

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
    vfx.log_info("Queued WhatsApp greeting task", colors=Colors)


async def delete_notification_files(notifications: list[vm.Notification]) -> None:
    paths = vu.extract_paths_to_delete(notifications)
    results = vfx.delete_files(paths)

    for path, success in results.items():
        if not success:
            vfx.log_error(f"Failed to delete notification: {path}", colors=Colors)


async def preserve_memory(state: vm.State, *, config: vm.VestaSettings) -> None:
    if config.ephemeral:
        vfx.log_info("Skipping memory preservation (ephemeral mode)", colors=Colors)
        return

    vfx.log_info(f"Preserving memory (timeout {config.memory_agent_timeout}s)...", colors=Colors)

    def log_progress(message: str) -> None:
        vfx.log_info(f"Memory agent: {message}", colors=Colors)

    start_time = dt.datetime.now()

    async def heartbeat() -> None:
        try:
            while True:
                await asyncio.sleep(30)
                elapsed = int((dt.datetime.now() - start_time).total_seconds())
                vfx.log_info(f"Memory agent still running... {elapsed}s elapsed", colors=Colors)
        except asyncio.CancelledError:
            pass

    heartbeat_task = asyncio.create_task(heartbeat())

    try:
        # Pass None to load conversation history from CLI session files
        diff = await vma.preserve_conversation_memory(None, config=config, progress_callback=log_progress)
        if diff:
            vfx.print_line(f"\n{Colors['cyan']}{Messages.MEMORY_UPDATED}{Colors['reset']}")
            vfx.print_line(diff)
        else:
            vfx.log_info("Memory agent found no significant updates", colors=Colors)
    except Exception as e:
        vfx.log_error(f"Memory preservation failed: {e}", colors=Colors)
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task


async def output_line(text: str, state: vm.State, *, is_tool: bool = False) -> None:
    if not text or not text.strip():
        return

    line_type = vu.classify_output_line(text, sub_agent_context=state.sub_agent_context, is_tool=is_tool)

    if line_type == "message":
        sender = f"Vesta[{state.sub_agent_context}]" if state.sub_agent_context else "Vesta"
        await print_timestamp_message(text, sender, lock=state.output_lock)
    else:
        formatted = vu.format_output_line(text, line_type=line_type, sub_agent_context=state.sub_agent_context, colors=Colors)
        await vfx.print_locked(state.output_lock, formatted, flush=True)


async def print_timestamp_message(text: str, sender: str, *, lock: "asyncio.Lock") -> None:
    timestamp = vfx.get_current_time()
    formatted_lines = vu.format_timestamp_message(text, sender, timestamp, colors=Colors)
    await vfx.render_messages_locked(lock, lines=formatted_lines)


async def send_query(client: ccsdk.ClaudeSDKClient, prompt: str, state: vm.State, *, config: vm.VestaSettings) -> vm.State:
    debug_log("🔍 [QUERY] Starting send_query", config=config)
    debug_log(f"🔍 [QUERY] Client exists: {client is not None}", config=config)
    debug_log(f"🔍 [QUERY] State.client exists: {state.client is not None}", config=config)

    timestamp = vfx.get_current_time()
    query_with_context = vu.build_query_with_timestamp(prompt, timestamp=timestamp)

    debug_log(f"🔍 [QUERY] Calling client.query() with {len(query_with_context)} chars", config=config)
    await client.query(query_with_context)
    debug_log("🔍 [QUERY] client.query() returned successfully", config=config)

    return state


async def collect_responses(
    client: ccsdk.ClaudeSDKClient, *, state: vm.State, config: vm.VestaSettings, show_output: bool = True
) -> tuple[list[str], vm.State]:
    debug_log("🔍 [COLLECT] Starting collect_responses", config=config)
    responses = []
    should_restart_client = False

    async def collect():
        debug_log("🔍 [COLLECT] Starting receive_response loop", config=config)
        try:
            async for msg in client.receive_response():
                debug_log(f"🔍 [COLLECT] Received message: {type(msg).__name__}", config=config)
                text, _, usage_data = parse_assistant_message(msg, state=state, config=config)

                if text:
                    if show_output:
                        for line in text.split("\n"):
                            if line.strip():
                                if line.startswith("🔧"):
                                    await output_line(line, state, is_tool=True)
                                else:
                                    responses.append(line)
            debug_log("🔍 [COLLECT] receive_response loop completed normally", config=config)
        except asyncio.CancelledError:
            debug_log("🔍 [COLLECT] receive_response loop caught CancelledError", config=config)
            raise
        except Exception as e:
            if config.debug:
                vfx.log_error(f"🔍 [COLLECT] receive_response loop error: {type(e).__name__}: {e}", colors=Colors)
            raise

    debug_log("🔍 [COLLECT] Creating collect task", config=config)
    collect_task = asyncio.create_task(collect())

    try:
        debug_log("🔍 [COLLECT] Waiting for collect task", config=config)
        await asyncio.wait_for(collect_task, timeout=config.response_timeout)
        debug_log("🔍 [COLLECT] collect task completed successfully", config=config)
    except asyncio.TimeoutError:
        debug_log("🔍 [COLLECT] collect task timed out", config=config)
        responses.append("[Response timeout]")
        state.sub_agent_context = None
        # Interrupt first to follow SDK pattern, then cancel
        await attempt_interrupt(state, config=config, reason="Response timeout")
        collect_task.cancel()
        should_restart_client = True
    except Exception:
        state.sub_agent_context = None
        await attempt_interrupt(state, config=config, reason="Response stream error")
        should_restart_client = True
    finally:
        debug_log("🔍 [COLLECT] Entering finally block", config=config)
        await settle_collect_task(collect_task, timeout=config.interrupt_timeout, config=config)
        debug_log("🔍 [COLLECT] settle_collect_task returned", config=config)

    if should_restart_client:
        # Check if restart is already in progress to prevent cascading restarts
        debug_log(f"🔍 [COLLECT] should_restart_client=True, is_restarting={state.is_restarting}", config=config)
        if state.is_restarting:
            debug_log("🔍 [COLLECT] Restart already in progress, skipping", config=config)
            responses.append("[Waiting for restart to complete...]")
        else:
            state.is_restarting = True
            try:
                debug_log("🔍 [COLLECT] Attempting to acquire restart_lock", config=config)
                async with state.restart_lock:
                    debug_log("🔍 [COLLECT] restart_lock acquired", config=config)
                    try:
                        await asyncio.wait_for(restart_claude_session(state, config=config), timeout=config.restart_timeout)
                    except asyncio.TimeoutError:
                        state.client = None
                        responses.append(f"[Error: Client restart timed out after {config.restart_timeout}s - please restart vesta]")
                        vfx.log_error(f"Client restart timed out after {config.restart_timeout} seconds", colors=Colors)
                    except Exception as e:
                        state.client = None
                        responses.append(f"[Error: Client restart failed - {str(e)[:50]}]")
                        vfx.log_error(f"Client restart failed: {e}", colors=Colors)
            finally:
                state.is_restarting = False

    return responses, state


async def send_and_receive_message(
    prompt: str, *, state: vm.State, config: vm.VestaSettings, show_in_chat: bool = True
) -> tuple[list[str], vm.State]:
    debug_log("🔍 [SEND-RECV] Starting send_and_receive_message", config=config)
    debug_log(f"🔍 [SEND-RECV] Client state: {state.client is not None}", config=config)

    if not state.client:
        # Attempt automatic recovery
        debug_log("🔍 [SEND-RECV] Client is None, attempting automatic recovery...", config=config)

        # Check if restart is already in progress
        if state.is_restarting:
            debug_log("🔍 [SEND-RECV] Restart already in progress, waiting...", config=config)
            # Wait briefly for restart to complete
            await asyncio.sleep(1.0)
            if not state.client:
                return ["[Waiting for restart to complete...]"], state
        else:
            state.is_restarting = True
            try:
                debug_log("🔍 [SEND-RECV] Attempting to acquire restart_lock", config=config)
                async with state.restart_lock:
                    debug_log("🔍 [SEND-RECV] restart_lock acquired", config=config)
                    try:
                        await asyncio.wait_for(restart_claude_session(state, config=config), timeout=config.restart_timeout)
                    except asyncio.TimeoutError:
                        error_msg = f"[Error: Cannot recover client - restart timed out after {config.restart_timeout}s. Please restart vesta manually]"
                        vfx.log_error("Client recovery timed out", colors=Colors)
                        return [error_msg], state
                    except Exception as e:
                        error_msg = f"[Error: Cannot recover client - {str(e)[:50]}. Please restart vesta manually]"
                        vfx.log_error(f"Client recovery failed: {e}", colors=Colors)
                        return [error_msg], state

                    if not state.client:
                        error_msg = "[Error: Client recovery failed. Please restart vesta manually]"
                        return [error_msg], state

                    vfx.log_success("✅ 🔍 [SEND-RECV] Client recovered successfully", colors=Colors)
            finally:
                state.is_restarting = False

    debug_log("🔍 [SEND-RECV] Calling send_query", config=config)
    try:
        await send_query(state.client, prompt, state, config=config)
        debug_log("🔍 [SEND-RECV] send_query completed successfully", config=config)
    except Exception as e:
        error_msg = f"failed to send message: {str(e)[:100]}"
        if config.debug:
            vfx.log_error(f"🔍 [SEND-RECV] send_query failed: {error_msg}", colors=Colors)
            traceback.print_exc()
        return [error_msg], state

    debug_log("🔍 [SEND-RECV] Calling collect_responses", config=config)
    responses, _ = await collect_responses(state.client, state=state, config=config, show_output=show_in_chat)
    debug_log(f"🔍 [SEND-RECV] collect_responses returned {len(responses)} responses", config=config)

    return responses, state


async def show_typing_indicator(config: vm.VestaSettings, *, lock: "asyncio.Lock") -> None:
    timestamp_str = vfx.get_timestamp_string(format="%I:%M %p")
    dots = ["   ", ".  ", ".. ", "..."]
    dot_idx = 0

    while True:
        await vfx.print_inline_locked(
            lock,
            text=f"\r{Colors['dim']}[{timestamp_str}]{Colors['reset']} {Colors['magenta']}vesta{Colors['reset']} {Colors['dim']}is typing{dots[dot_idx]}{Colors['reset']}",
        )
        dot_idx = (dot_idx + 1) % 4
        await vfx.sleep(config.typing_animation_delay)


async def process_message_with_typing(msg: str, state: vm.State, config: vm.VestaSettings, *, is_user: bool) -> tuple[list[str], vm.State]:
    debug_log(f"🔍 [TYPING] Starting process_message_with_typing", config=config)
    now = vfx.get_current_time()
    await vfx.sleep(config.pre_typing_delay + now.microsecond / 3000000)

    debug_log("🔍 [TYPING] Starting typing indicator", config=config)
    typing_task = asyncio.create_task(show_typing_indicator(config, lock=state.output_lock))
    try:
        debug_log("🔍 [TYPING] Calling send_and_receive_message", config=config)
        responses, new_state = await send_and_receive_message(msg, state=state, config=config, show_in_chat=is_user)
        debug_log(f"🔍 [TYPING] send_and_receive_message returned {len(responses)} responses", config=config)
    except Exception as e:
        responses = [f"something went wrong: {str(e)[:50]}"]
        vfx.log_error(f"Message processing error: {str(e)[:100]}", colors=Colors)
        new_state = state
    finally:
        typing_task.cancel()
        try:
            # Don't wait indefinitely for typing task to cancel - add timeout to prevent deadlock
            await asyncio.wait_for(typing_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass  # Task cancelled or abandoned
        await vfx.clear_line_locked(state.output_lock)

    return responses, new_state


async def handle_notifications_interrupt(
    notifications: list[vm.Notification], queue: asyncio.Queue, state: vm.State, config: vm.VestaSettings, *, lock: "asyncio.Lock"
) -> None:
    debug_log(f"🔍 [NOTIF-INT] Entering handle_notifications_interrupt with {len(notifications)} notifications", config=config)
    await vfx.print_locked(lock, f"\n{Colors['yellow']}{Messages.INTERRUPTING_TASK}{Colors['reset']}", flush=False)

    prompt = vu.format_notification_batch(notifications)
    success = await attempt_interrupt(state, config=config, reason="Notification interrupt")

    if not success:
        debug_log("🔍 [NOTIF-INT] Interrupt failed", config=config)
        await vfx.print_locked(
            lock,
            f"{Colors['yellow']}⚠️ Could not interrupt current task; queued notification for later.{Colors['reset']}",
            flush=False,
        )
    else:
        debug_log("🔍 [NOTIF-INT] Interrupt succeeded", config=config)

    # Queue the notification — even if interrupt failed we'll process it later
    debug_log(f"🔍 [NOTIF-INT] Queuing notification prompt (length: {len(prompt)} chars)", config=config)
    await queue.put((prompt, True))
    debug_log("🔍 [NOTIF-INT] Notification queued, exiting handle_notifications_interrupt", config=config)


async def process_notification_batch(
    notifications: list[vm.Notification], queue: asyncio.Queue, state: vm.State, *, config: vm.VestaSettings
) -> None:
    if not notifications:
        return

    try:
        decision = vu.decide_notification_action(notifications, is_processing=state.is_processing, has_client=state.client is not None)

        if decision == "interrupt" and state.client:
            await handle_notifications_interrupt(notifications, queue, state, config, lock=state.output_lock)
        elif decision == "queue":
            prompt = vu.format_notification_batch(notifications)
            await queue.put((prompt, True))

        await delete_notification_files(notifications)
    except Exception as e:
        vfx.log_error(f"Failed to process notification batch: {e}", colors=Colors)
        traceback.print_exc()


def signal_handler(state: vm.State, config: vm.VestaSettings, signum: int, frame: tp.Any) -> None:
    with state.shutdown_lock:
        state.shutdown_count += 1
        if state.shutdown_count == 1:
            vfx.print_line(f"\n{Colors['dim']}{Messages.SHUTDOWN_INITIATED}{Colors['reset']}")
            if state.shutdown_event:
                state.shutdown_event.set()
        elif state.shutdown_count > 2:
            vfx.print_line(f"\n{Colors['yellow']}{Messages.FORCE_SHUTDOWN}{Colors['reset']}")
            vfx.exit_process(0)


async def graceful_shutdown(state: vm.State, *, config: vm.VestaSettings) -> None:
    # Always try to preserve memory on shutdown
    try:
        await asyncio.wait_for(preserve_memory(state, config=config), timeout=config.memory_agent_timeout)
    except asyncio.TimeoutError:
        vfx.log_error("Memory preservation timeout", colors=Colors)
    except Exception as e:
        vfx.log_error(f"Memory error: {e}", colors=Colors)

    if state.client:
        try:
            await state.client.__aexit__(None, None, None)
        except Exception:
            pass

    # Unmount OneDrive if it was mounted
    if config.onedrive_dir.exists() and config.onedrive_token:
        try:
            vod.unmount_onedrive(config.onedrive_dir)
        except Exception as e:
            vfx.log_error(f"Failed to unmount OneDrive: {e}", colors=Colors)

    vfx.log_success(Messages.SHUTDOWN_COMPLETE, colors=Colors)


async def print_header(config: vm.VestaSettings, *, lock: "asyncio.Lock") -> None:
    await vfx.print_locked(lock, f"\n{Colors['cyan']}{Formats.BOX_TOP}", flush=False)
    await vfx.print_locked(
        lock,
        f"{Formats.BOX_MIDDLE_LEFT}{' ' * 23}{Colors['yellow']}{Emoji.FIRE} VESTA{Colors['cyan']}{' ' * 27}{Formats.BOX_MIDDLE_RIGHT}",
        flush=False,
    )
    await vfx.print_locked(lock, f"{Formats.BOX_BOTTOM}{Colors['reset']}\n", flush=False)
    if config.mcp_servers:
        await vfx.print_locked(lock, f"{Colors['dim']}Active MCPs: {', '.join(config.mcp_servers.keys())}{Colors['reset']}\n", flush=False)


def ensure_memory_file(config: vm.VestaSettings) -> None:
    if not config.memory_file.exists() and config.memory_template.exists():
        shutil.copy(config.memory_template, config.memory_file)
        vfx.log_info("Created MEMORY.md from template", colors=Colors)


async def message_processor(queue: asyncio.Queue, state: vm.State, *, config: vm.VestaSettings) -> None:
    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            msg, is_user = await asyncio.wait_for(queue.get(), timeout=1.0)
            debug_log(f"🔍 [PROCESSOR] Picked up message from queue (is_user={is_user}, length={len(msg)} chars)", config=config)

            async with state.processing_lock:
                state.is_processing = True

            try:
                debug_log("🔍 [PROCESSOR] Processing message", config=config)
                responses, _ = await process_message_with_typing(msg, state, config, is_user=is_user)
                debug_log(f"🔍 [PROCESSOR] Processing completed with {len(responses)} responses", config=config)

                for i, response in enumerate(responses):
                    if response and response.strip():
                        if i > 0:
                            await vfx.sleep(config.response_spacing_delay)
                        await output_line(response, state)
            finally:
                async with state.processing_lock:
                    state.is_processing = False

        except asyncio.TimeoutError:
            continue
        except Exception as e:
            vfx.log_error(f"Queue error: {str(e)[:100]}", colors=Colors)
            traceback.print_exc()
            async with state.processing_lock:
                state.is_processing = False


async def input_handler(queue: asyncio.Queue, *, state: vm.State) -> None:
    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            user_msg = await aioconsole.ainput(f"{Colors['green']}>{Colors['reset']} ")
            if state.shutdown_event and state.shutdown_event.is_set():
                break
            if not user_msg.strip():
                continue

            await vfx.move_cursor_up_and_clear_locked(state.output_lock)
            await print_timestamp_message(user_msg, "You", lock=state.output_lock)
            await queue.put((user_msg.strip(), True))
        except (KeyboardInterrupt, EOFError):
            if state.shutdown_event:
                state.shutdown_event.set()
            break
        except asyncio.CancelledError:
            break
        except BlockingIOError:
            # Handle non-blocking I/O errors gracefully
            await asyncio.sleep(0.1)
            continue
        except OSError as e:
            if e.errno == errno.EAGAIN or e.errno == errno.EWOULDBLOCK:  # Resource temporarily unavailable
                await asyncio.sleep(0.1)
                continue
            else:
                raise


async def check_proactive_task(queue: asyncio.Queue, state: vm.State, *, config: vm.VestaSettings) -> None:
    await print_timestamp_message(Messages.PROACTIVE_CHECK, Senders.SYSTEM, lock=state.output_lock)
    await queue.put((config.proactive_check_message, False))


async def process_nightly_memory(state: vm.State, *, config: vm.VestaSettings) -> None:
    now = vfx.get_current_time()
    if config.enable_nightly_memory and now.hour >= config.nightly_memory_time:
        if state.last_memory_consolidation is None or now.date() > state.last_memory_consolidation.date():
            await print_timestamp_message(Messages.NIGHTLY_MEMORY, Senders.SYSTEM, lock=state.output_lock)
            await preserve_memory(state, config=config)
            state.last_memory_consolidation = now


async def load_and_display_new_notifications(
    notification_buffer: list[vm.Notification], *, buffer_start_time: dt.datetime | None, state: vm.State, config: vm.VestaSettings
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
                    icon, sender, display_msg = notif.get_display_info()
                    await print_timestamp_message(f"{icon} {display_msg}", sender, lock=state.output_lock)
    except Exception as e:
        vfx.log_error(f"Error loading notifications: {e}", colors=Colors)
        traceback.print_exc()

    return notification_buffer, buffer_start_time


async def monitor_loop(queue: asyncio.Queue, state: vm.State, *, config: vm.VestaSettings) -> None:
    last_proactive = vfx.get_current_time()
    notification_buffer = []
    buffer_start_time = None

    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            await vfx.sleep(config.notification_check_interval)
        except asyncio.CancelledError:
            break
        except Exception as e:
            vfx.log_error(f"Monitor loop sleep error: {e}", colors=Colors)
            continue

        if state.shutdown_event and state.shutdown_event.is_set():
            break

        try:
            now = vfx.get_current_time()

            try:
                actions = vu.calculate_monitoring_actions(now, last_proactive, config=config)
            except Exception as e:
                vfx.log_error(f"Error in calculate_monitoring_actions: {e}", colors=Colors)
                traceback.print_exc()
                actions = []

            for action in actions:
                if action.action_type == "check_proactive":
                    await check_proactive_task(queue, state, config=config)
                    last_proactive = now

            await process_nightly_memory(state, config=config)

            notification_buffer, buffer_start_time = await load_and_display_new_notifications(
                notification_buffer, buffer_start_time=buffer_start_time, state=state, config=config
            )

            if vu.should_process_notification_buffer(
                notification_buffer, buffer_start_time, now, buffer_delay=config.notification_buffer_delay
            ):
                try:
                    await process_notification_batch(notification_buffer, queue, state, config=config)
                    notification_buffer = []
                    buffer_start_time = None
                except Exception as e:
                    vfx.log_error(f"Error processing notifications: {e}", colors=Colors)
                    traceback.print_exc()
                    notification_buffer = []
                    buffer_start_time = None

        except Exception as e:
            vfx.log_error(f"CRITICAL: Monitor loop iteration crashed: {e}", colors=Colors)
            traceback.print_exc()
            continue


async def run_vesta(config: vm.VestaSettings, *, state: vm.State) -> None:
    state.shutdown_event = asyncio.Event()

    handler = functools.partial(signal_handler, state, config)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    ensure_memory_file(config)
    await print_header(config, lock=state.output_lock)

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
        vfx.log_error("Shutdown timeout", colors=Colors)


def check_dependencies() -> None:
    if shutil.which("npm") is None:
        raise RuntimeError("npm is not found in PATH. Please install Node.js and npm: https://nodejs.org/")

    if shutil.which("uv") is None:
        raise RuntimeError("uv is not found in PATH. Please install uv: https://docs.astral.sh/uv/getting-started/installation/")

    if not vod.check_rclone_installed():
        raise RuntimeError("rclone is not found in PATH. Please install rclone: https://rclone.org/install/")


async def create_claude_client(config: vm.VestaSettings, resume_session_id: str | None = None) -> ccsdk.ClaudeSDKClient:
    """Create and enter a Claude SDK client session, optionally resuming a previous session."""
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
    # Add timeout to prevent infinite hang during client initialization
    await asyncio.wait_for(client.__aenter__(), timeout=config.restart_timeout)
    return client


async def restart_claude_session(state: vm.State, *, config: vm.VestaSettings) -> None:
    """Recreate the Claude client so a bad tool run doesn't brick Vesta."""
    # Check if shutdown is in progress
    if state.shutdown_event and state.shutdown_event.is_set():
        vfx.log_info("Skipping restart - shutdown in progress", colors=Colors)
        return

    old_process_pid = None
    if state.client:
        # Capture subprocess PID before losing reference
        try:
            if hasattr(state.client, "_transport") and state.client._transport:
                if hasattr(state.client._transport, "_process") and state.client._transport._process:
                    old_process_pid = state.client._transport._process.pid
        except Exception:
            pass  # Best effort

        try:
            await asyncio.wait_for(state.client.__aexit__(None, None, None), timeout=config.interrupt_timeout)
        except asyncio.TimeoutError:
            vfx.log_error(f"Client exit timed out after {config.interrupt_timeout}s", colors=Colors)
            # Force kill the subprocess if we have its PID
            if old_process_pid:
                try:
                    os.kill(old_process_pid, signal.SIGKILL)
                    vfx.log_info(f"Force killed subprocess {old_process_pid}", colors=Colors)
                except ProcessLookupError:
                    pass  # Process already dead
                except Exception as e:
                    vfx.log_error(f"Failed to kill subprocess: {e}", colors=Colors)
        except Exception as e:
            vfx.log_error(f"Error while closing Claude client: {e}", colors=Colors)
        finally:
            state.client = None

    try:
        # Resume the previous session to preserve conversation context
        state.client = await create_claude_client(config, resume_session_id=state.session_id)
        state.sub_agent_context = None
        vfx.log_info(f"Restarted client{' (resuming session ' + state.session_id + ')' if state.session_id else ''}", colors=Colors)
    except Exception as e:
        vfx.log_error(f"Failed to recreate Claude client: {e}", colors=Colors)


async def init_state(*, config: vm.VestaSettings) -> vm.State:
    """Initialize a fresh Vesta state with all required fields, including the client."""
    # Create the Claude SDK client
    client = await create_claude_client(config)

    # Initialize state with the client
    now = vfx.get_current_time()
    return vm.State(
        client=client,
        shutdown_event=None,
        shutdown_lock=threading.Lock(),
        shutdown_count=0,
        is_processing=False,
        sub_agent_context=None,
        last_memory_consolidation=now,
    )


async def async_main() -> None:
    # Initialize configuration
    config = vm.VestaSettings()

    # Set up OneDrive mount if configured
    if config.onedrive_token:
        try:
            vfx.log_info("Setting up OneDrive mount...", colors=Colors)
            vod.setup_rclone_config(config, config_path=config.rclone_config_file)
            await vod.mount_onedrive(config, config.onedrive_dir, config.rclone_config_file)
            vfx.log_success(f"OneDrive mounted at {config.onedrive_dir}", colors=Colors)
        except Exception as e:
            raise RuntimeError(f"Failed to mount OneDrive: {e}") from e

    # Initialize state with client
    initial_state = await init_state(config=config)

    # Run Vesta
    await run_vesta(config, state=initial_state)


def main() -> None:
    check_dependencies()

    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        vfx.print_line(f"\n💥 Fatal error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
