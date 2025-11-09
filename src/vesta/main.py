import asyncio
import datetime as dt
import errno
import functools
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


async def attempt_interrupt(state: vm.State, *, config: vm.VestaSettings, reason: str) -> bool:
    """Best-effort interrupt with a short timeout so we don't hang indefinitely."""
    if not state.client:
        return False

    try:
        await asyncio.wait_for(state.client.interrupt(), timeout=config.interrupt_timeout)
        vfx.log_info(f"{reason}: interrupt sent", colors=Colors)
        return True
    except asyncio.TimeoutError:
        vfx.log_error(
            f"{reason}: interrupt timed out after {config.interrupt_timeout} seconds (tool may still be running)",
            colors=Colors,
        )
    except Exception as e:
        vfx.log_error(f"{reason}: interrupt failed ({str(e)[:120]})", colors=Colors)
        traceback.print_exc()
    return False


def parse_assistant_message(msg: tp.Any, *, state: vm.State) -> tuple[str | None, vm.State, dict[str, tp.Any] | None]:
    texts, new_context, usage_data = vu.parse_assistant_message(msg, state.sub_agent_context, service_icons=vm.SERVICE_ICONS)
    state.sub_agent_context = new_context
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
                notifications.append(notif)
            except Exception as e:
                vfx.log_error(f"Failed to read notification {file.name}: {e}", colors=Colors)

    return notifications


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

    if not state.conversation_history:
        vfx.log_info("No conversation history to preserve", colors=Colors)
        return

    vfx.log_info(f"Preserving {len(state.conversation_history)} messages...", colors=Colors)
    try:
        diff = await vma.preserve_conversation_memory(state.conversation_history, config=config)
        if diff:
            vfx.print_line(f"\n{Colors['cyan']}{Messages.MEMORY_UPDATED}{Colors['reset']}")
            vfx.print_line(diff)
        else:
            vfx.log_info("Memory agent found no significant updates", colors=Colors)
    except Exception as e:
        vfx.log_error(f"Memory preservation failed: {e}", colors=Colors)


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
    timestamp = vfx.get_current_time()
    query_with_context = vu.build_query_with_timestamp(prompt, timestamp=timestamp)
    state.conversation_history = vu.add_to_conversation_history(state.conversation_history, "user", content=prompt)

    await client.query(query_with_context)

    return state


async def collect_responses(
    client: ccsdk.ClaudeSDKClient, *, state: vm.State, config: vm.VestaSettings, show_output: bool = True
) -> tuple[list[str], vm.State]:
    responses = []
    message_count = 0

    async def collect():
        nonlocal message_count
        try:
            async for msg in client.receive_response():
                message_count += 1
                text, _, usage_data = parse_assistant_message(msg, state=state)

                if text:
                    if show_output:
                        for line in text.split("\n"):
                            if line.strip():
                                if line.startswith("🔧"):
                                    await output_line(line, state, is_tool=True)
                                else:
                                    responses.append(line)
        except Exception:
            raise

    try:
        await asyncio.wait_for(collect(), timeout=config.response_timeout)
    except asyncio.TimeoutError:
        responses.append("[Response timeout]")
        state.sub_agent_context = None
        await attempt_interrupt(state, config=config, reason="Response timeout")
    except asyncio.CancelledError:
        state.sub_agent_context = None
    except Exception:
        state.sub_agent_context = None
        await attempt_interrupt(state, config=config, reason="Response stream error")

    return responses, state


async def send_and_receive_message(
    prompt: str, *, state: vm.State, config: vm.VestaSettings, show_in_chat: bool = True
) -> tuple[list[str], vm.State]:
    if not state.client:
        raise RuntimeError("Client not initialized")

    try:
        await send_query(state.client, prompt, state, config=config)
    except Exception as e:
        error_msg = f"failed to send message: {str(e)[:100]}"
        vfx.log_error(error_msg, colors=Colors)
        traceback.print_exc()
        state.conversation_history = vu.add_to_conversation_history(state.conversation_history, "assistant", content=error_msg)
        return [error_msg], state

    responses, _ = await collect_responses(state.client, state=state, config=config, show_output=show_in_chat)

    if responses:
        state.conversation_history = vu.add_to_conversation_history(state.conversation_history, "assistant", content=" ".join(responses))

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
    now = vfx.get_current_time()
    await vfx.sleep(config.pre_typing_delay + now.microsecond / 3000000)

    typing_task = asyncio.create_task(show_typing_indicator(config, lock=state.output_lock))
    try:
        responses, new_state = await send_and_receive_message(msg, state=state, config=config, show_in_chat=is_user)
    except Exception as e:
        responses = [f"something went wrong: {str(e)[:50]}"]
        vfx.log_error(f"Message processing error: {str(e)[:100]}", colors=Colors)
        new_state = state
    finally:
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass
        await vfx.clear_line_locked(state.output_lock)

    return responses, new_state


async def handle_notifications_interrupt(
    notifications: list[vm.Notification], queue: asyncio.Queue, state: vm.State, config: vm.VestaSettings, *, lock: "asyncio.Lock"
) -> None:
    await vfx.print_locked(lock, f"\n{Colors['yellow']}{Messages.INTERRUPTING_TASK}{Colors['reset']}", flush=False)

    prompt = vu.format_notification_batch(notifications)
    success = await attempt_interrupt(state, config=config, reason="Notification interrupt")

    if not success:
        await vfx.print_locked(
            lock,
            f"{Colors['yellow']}⚠️ Could not interrupt current task; queued notification for later.{Colors['reset']}",
            flush=False,
        )

    # Queue the notification — even if interrupt failed we'll process it later
    await queue.put((prompt, True))


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

            state.is_processing = True

            responses, _ = await process_message_with_typing(msg, state, config, is_user=is_user)

            for i, response in enumerate(responses):
                if response and response.strip():
                    if i > 0:
                        await vfx.sleep(config.response_spacing_delay)
                    await output_line(response, state)

            state.is_processing = False
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            vfx.log_error(f"Queue error: {str(e)[:100]}", colors=Colors)
            traceback.print_exc()
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


async def init_state(*, config: vm.VestaSettings) -> vm.State:
    """Initialize a fresh Vesta state with all required fields, including the client."""
    # Create the Claude SDK client
    client = ccsdk.ClaudeSDKClient(
        options=ccsdk.ClaudeCodeOptions(
            system_prompt=load_system_prompt(config),
            mcp_servers=tp.cast(dict[str, ccsdk_types.McpServerConfig], config.mcp_servers),
            hooks={},
            permission_mode="bypassPermissions",
            model="sonnet",
        )
    )
    await client.__aenter__()

    # Initialize state with the client
    return vm.State(
        client=client,
        conversation_history=[],
        shutdown_event=None,
        shutdown_lock=threading.Lock(),
        shutdown_count=0,
        is_processing=False,
        sub_agent_context=None,
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
