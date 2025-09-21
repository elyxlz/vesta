import asyncio
import functools
import os
import signal
import pathlib as pl
import typing as tp

import aioconsole
import claude_code_sdk as ccsdk
import claude_code_sdk.types as ccsdk_types

import vesta.memory_agent as vma
import vesta.models as vm
import vesta.utils as vu
import vesta.effects as vfx


def get_root_path() -> pl.Path:
    return pl.Path(__file__).parent.parent.parent.absolute()


def load_system_prompt() -> str:
    memory_path = get_root_path() / "MEMORY.md"
    if not memory_path.exists():
        raise FileNotFoundError(f"MEMORY.md not found at {memory_path}")
    return memory_path.read_text()


async def check_mcp_health(client: ccsdk.ClaudeSDKClient) -> None:
    await client.query("")
    found_init = False
    async for msg in client.receive_response():
        if not found_init and hasattr(msg, "subtype") and msg.subtype == "init":
            mcp_servers = msg.data.get("mcp_servers", [])
            failed_mcps = [server["name"] for server in mcp_servers if server.get("status") == "failed"]

            if failed_mcps:
                error_msg = f"Failed to connect to MCP servers: {', '.join(failed_mcps)}"
                vfx.log_error(error_msg, vm.Colors)
                raise RuntimeError(error_msg)

            connected_mcps = [server["name"] for server in mcp_servers if server.get("status") == "connected"]
            if connected_mcps:
                vfx.log_success(f"Connected to MCPs: {', '.join(connected_mcps)}", vm.Colors)
            found_init = True
            break  # Exit after finding init message - don't wait forever!


async def init_client(state: vm.State, config: vm.VestaSettings) -> tuple[ccsdk.ClaudeSDKClient, vm.State]:
    if state.client:
        if config.debug:
            vfx.log_info("[DEBUG] Reusing existing client", vm.Colors)
        return state.client, state

    client = ccsdk.ClaudeSDKClient(
        options=ccsdk.ClaudeCodeOptions(
            system_prompt=load_system_prompt(),
            mcp_servers=tp.cast(dict[str, ccsdk_types.McpServerConfig], config.mcp_servers),
            hooks={},
            model="opus",
            permission_mode="bypassPermissions",
        )
    )
    await client.__aenter__()

    if config.debug:
        vfx.log_info("[DEBUG] Claude SDK client initialized", vm.Colors)

    await check_mcp_health(client)

    new_state = vu.update_state(state, client=client)
    return client, new_state


def format_tool_call(name: str, input_data: tp.Any, state: vm.State) -> tuple[str, vm.State]:
    formatted, new_context = vu.format_tool_call(name, input_data, state.sub_agent_context, vm.SERVICE_ICONS)
    new_state = vu.update_state(state, sub_agent_context=new_context) if new_context != state.sub_agent_context else state
    return formatted, new_state


def parse_assistant_message(msg: tp.Any, state: vm.State) -> tuple[str | None, vm.State]:
    texts, new_context = vu.parse_assistant_message(msg, state.sub_agent_context, vm.SERVICE_ICONS)
    new_state = vu.update_state(state, sub_agent_context=new_context)
    return "\n".join(texts) if texts else None, new_state


def format_notification(notif: vm.Notification) -> str:
    return notif.format_for_display()


async def load_notifications() -> list[vm.Notification]:
    notif_dir = get_root_path() / "notifications"
    file_contents = vfx.load_notification_files(notif_dir)

    notifications = []
    for file, content in file_contents:
        if content:
            try:
                data = vu.parse_notification_file_content(content)
                notif = vm.Notification(**data)
                notif.file_path = str(file)
                notifications.append(notif)
            except Exception as e:
                vfx.log_error(f"Failed to read notification {file.name}: {e}", vm.Colors)

    return notifications


async def delete_notification_files(notifications: list[vm.Notification]) -> None:
    paths = vu.extract_paths_to_delete(notifications)
    results = vfx.delete_files(paths)

    for path, success in results.items():
        if not success:
            vfx.log_error(f"Failed to delete notification: {path}", vm.Colors)


async def preserve_memory(state: vm.State, config: vm.VestaSettings) -> None:
    if config.ephemeral or not state.conversation_history:
        return

    try:
        diff = await vma.preserve_conversation_memory(state.conversation_history)
        if diff:
            vfx.print_line(f"\n{vm.Colors['cyan']}📝 Memory updated:{vm.Colors['reset']}")
            vfx.print_line(diff)
    except Exception as e:
        vfx.log_error(f"Memory preservation failed: {e}", vm.Colors)


async def check_context_and_preserve(state: vm.State, config: vm.VestaSettings) -> vm.State:
    if vu.should_preserve_memory(state.conversation_history, config.max_context_tokens, config.ephemeral):
        vfx.print_line(f"{vm.Colors['yellow']}📊 Context limit reached, preserving memory...{vm.Colors['reset']}")
        await preserve_memory(state, config)
        new_state = vu.update_state(state, conversation_history=[])
        vfx.log_success("Context cleared, continuing...", vm.Colors)
        return new_state
    return state


def output_line(text: str, state: vm.State, is_tool: bool = False) -> None:
    if not text or not text.strip():
        return

    line_type = vu.classify_output_line(text, state.sub_agent_context, is_tool)

    if line_type == "message":
        sender = f"Vesta[{state.sub_agent_context}]" if state.sub_agent_context else "Vesta"
        print_timestamp_message(text, sender)
    else:
        formatted = vu.format_output_line(text, line_type, state.sub_agent_context, vm.Colors)
        vfx.print_line(formatted, flush=True)


def print_timestamp_message(text: str, sender: str = "") -> None:
    timestamp = vfx.get_current_time()
    formatted_lines = vu.format_timestamp_message(text, sender, timestamp, vm.Colors)
    vfx.render_messages(formatted_lines)


def start_whatsapp_bridge() -> bool:
    script_path = get_root_path() / "start_whatsapp_bridge.sh"
    if not vfx.file_exists(script_path):
        return False

    returncode, _, _ = vfx.run_subprocess([str(script_path), "--force"])
    if returncode == 0:
        vfx.log_success("WhatsApp bridge connected", vm.Colors)
        return True
    return False


def is_whatsapp_bridge_running() -> bool:
    return vfx.check_process_running("whatsapp-bridge")


async def send_query(client: ccsdk.ClaudeSDKClient, prompt: str, state: vm.State, config: vm.VestaSettings) -> vm.State:
    timestamp = vfx.get_current_time()
    query_with_context = vu.build_query_with_timestamp(prompt, timestamp)
    new_history = vu.add_to_conversation_history(state.conversation_history, "user", prompt)
    new_state = vu.update_state(state, conversation_history=new_history)

    if config.debug:
        vfx.log_info(f"[DEBUG] Sending query: {prompt[:100]}...", vm.Colors)
        vfx.log_info(f"[DEBUG] Full query being sent: {query_with_context[:200]}...", vm.Colors)
        vfx.log_info(f"[DEBUG] Client before query: {client}", vm.Colors)

    await client.query(query_with_context)

    if config.debug:
        vfx.log_info(f"[DEBUG] Query sent successfully", vm.Colors)

    return await check_context_and_preserve(new_state, config)


async def collect_responses(
    client: ccsdk.ClaudeSDKClient, state: vm.State, config: vm.VestaSettings, show_output: bool = True
) -> tuple[list[str], vm.State]:
    responses = []
    current_state = state
    message_count = 0

    async def collect():
        nonlocal current_state, message_count
        if config.debug:
            vfx.log_info("[DEBUG] Starting to collect responses", vm.Colors)
            vfx.log_info(f"[DEBUG] Client state: {client}", vm.Colors)
            vfx.log_info(f"[DEBUG] Client type: {type(client)}", vm.Colors)
            if hasattr(client, '_connected'):
                vfx.log_info(f"[DEBUG] Client connected: {client._connected}", vm.Colors)
        try:
            if config.debug:
                vfx.log_info(f"[DEBUG] About to iterate over client.receive_response()", vm.Colors)
            iteration_started = False
            async for msg in client.receive_response():
                if not iteration_started and config.debug:
                    vfx.log_info(f"[DEBUG] Started receiving messages from client", vm.Colors)
                    iteration_started = True
                message_count += 1
                if config.debug:
                    vfx.log_info(f"[DEBUG] Received message #{message_count} type: {type(msg).__name__}", vm.Colors)
                    if hasattr(msg, '__dict__'):
                        vfx.log_info(f"[DEBUG] Message attributes: {list(msg.__dict__.keys())}", vm.Colors)
                text, new_state = parse_assistant_message(msg, current_state)
                current_state = new_state
                if config.debug and text:
                    vfx.log_info(f"[DEBUG] Got text from message: {text[:100]}", vm.Colors)

                # Check for stream end indicators
                if hasattr(msg, 'stop_reason'):
                    if config.debug:
                        vfx.log_info(f"[DEBUG] Message has stop_reason: {msg.stop_reason}", vm.Colors)
                if hasattr(msg, 'is_final'):
                    if config.debug:
                        vfx.log_info(f"[DEBUG] Message has is_final: {msg.is_final}", vm.Colors)

                if text:
                    if show_output:
                        for line in text.split("\n"):
                            if line.strip():
                                if line.startswith("🔧"):
                                    if config.debug:
                                        vfx.log_info(f"[DEBUG] Tool output (msg #{message_count}): {line[:100]}", vm.Colors)
                                    output_line(line, current_state, is_tool=True)
                                else:
                                    responses.append(line)
                                    output_line(line, current_state)
            if config.debug:
                vfx.log_info(f"[DEBUG] Finished iterating over responses normally, received {message_count} messages", vm.Colors)
        except Exception as e:
            if config.debug:
                vfx.log_info(f"[DEBUG] Error in collect loop: {str(e)}", vm.Colors)
            raise

    try:
        await asyncio.wait_for(collect(), timeout=config.response_timeout)
    except asyncio.TimeoutError:
        if config.debug:
            vfx.log_info(f"[DEBUG] Response collection timed out after {config.response_timeout}s", vm.Colors)
        responses.append("[Response timeout]")
        current_state = vu.update_state(current_state, sub_agent_context=None)
    except asyncio.CancelledError:
        if config.debug:
            vfx.log_info("[DEBUG] Response collection interrupted", vm.Colors)
        current_state = vu.update_state(current_state, sub_agent_context=None)
    except Exception as e:
        if config.debug:
            vfx.log_info(f"[DEBUG] Response collection error: {str(e)}", vm.Colors)
        current_state = vu.update_state(current_state, sub_agent_context=None)

    if config.debug:
        vfx.log_info(f"[DEBUG] Finished collecting {message_count} messages", vm.Colors)

    return responses, current_state


async def send_and_receive_message(
    prompt: str, state: vm.State, config: vm.VestaSettings, show_in_chat: bool = True
) -> tuple[list[str], vm.State]:
    if config.debug:
        vfx.log_info(f"[DEBUG] send_and_receive_message called with prompt: {prompt[:100]}", vm.Colors)

    client, new_state = await init_client(state, config)

    if config.debug:
        vfx.log_info(f"[DEBUG] Client initialized, about to send query", vm.Colors)

    try:
        new_state = await send_query(client, prompt, new_state, config)
    except Exception as e:
        error_msg = f"failed to send message: {str(e)[:100]}"
        vfx.log_error(error_msg, vm.Colors)
        if config.debug:
            import traceback
            traceback.print_exc()
        updated_history = vu.add_to_conversation_history(new_state.conversation_history, "assistant", error_msg)
        return [error_msg], vu.update_state(new_state, conversation_history=updated_history)

    responses, final_state = await collect_responses(client, new_state, config, show_in_chat)

    if config.debug:
        vfx.log_info(f"[DEBUG] Collected {len(responses)} responses", vm.Colors)

    if responses:
        updated_history = vu.add_to_conversation_history(final_state.conversation_history, "assistant", " ".join(responses))
        final_state = vu.update_state(final_state, conversation_history=updated_history)

    return responses, final_state


async def show_typing_indicator(config: vm.VestaSettings) -> None:
    timestamp_str = vfx.get_timestamp_string("%I:%M %p")
    dots = ["   ", ".  ", ".. ", "..."]
    dot_idx = 0

    while True:
        vfx.print_inline(
            f"\r{vm.Colors['dim']}[{timestamp_str}]{vm.Colors['reset']} {vm.Colors['magenta']}vesta{vm.Colors['reset']} {vm.Colors['dim']}is typing{dots[dot_idx]}{vm.Colors['reset']}"
        )
        dot_idx = (dot_idx + 1) % 4
        await vfx.sleep(config.typing_animation_delay)


async def process_message_with_typing(msg: str, state: vm.State, config: vm.VestaSettings, is_user: bool) -> tuple[list[str], vm.State]:
    if config.debug:
        vfx.log_info(f"[DEBUG] process_message_with_typing called", vm.Colors)
    now = vfx.get_current_time()
    await vfx.sleep(0.8 + now.microsecond / 3000000)

    if config.debug:
        vfx.log_info(f"[DEBUG] Creating typing indicator task", vm.Colors)
    typing_task = asyncio.create_task(show_typing_indicator(config))
    try:
        if config.debug:
            vfx.log_info(f"[DEBUG] About to call send_and_receive_message", vm.Colors)
        responses, new_state = await send_and_receive_message(msg, state, config, show_in_chat=is_user)
    except Exception as e:
        responses = [f"something went wrong: {str(e)[:50]}"]
        vfx.log_error(f"Message processing error: {str(e)[:100]}", vm.Colors)
        new_state = state
    finally:
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass
        vfx.clear_line()

    return responses, new_state


async def handle_notifications_interrupt(
    notifications: list[vm.Notification], client: ccsdk.ClaudeSDKClient, queue: asyncio.Queue, config: vm.VestaSettings
) -> None:
    vfx.print_line(f"\n{vm.Colors['yellow']}⚡ Interrupting current task...{vm.Colors['reset']}")

    try:
        await client.interrupt()

        # Queue the notification for processing after interrupt
        prompt = vu.format_notification_batch(notifications)
        await queue.put((prompt, True))

        if config.debug:
            vfx.log_info("[DEBUG] Interrupt sent, notification queued", vm.Colors)
    except Exception as e:
        vfx.log_error(f"Interrupt failed: {e}", vm.Colors)
        import traceback

        if config.debug:
            traceback.print_exc()
        raise


async def process_notification_batch(
    notifications: list[vm.Notification], queue: asyncio.Queue, state: vm.State, config: vm.VestaSettings
) -> vm.State:
    if not notifications:
        return state

    try:
        decision = vu.decide_notification_action(notifications, state.is_processing, state.client is not None)
        if config.debug:
            vfx.log_info(f"[DEBUG] Notification action decision: {decision}", vm.Colors)

        if decision == "interrupt" and state.client:
            await handle_notifications_interrupt(notifications, state.client, queue, config)
            new_state = state
        elif decision == "queue":
            prompt = vu.format_notification_batch(notifications)
            await queue.put((prompt, True))
            new_state = state
        else:
            new_state = state

        await delete_notification_files(notifications)
        return new_state
    except Exception as e:
        vfx.log_error(f"Failed to process notification batch: {e}", vm.Colors)
        import traceback

        if config.debug:
            traceback.print_exc()
        return state


def signal_handler(state: vm.State, config: vm.VestaSettings, signum: int, frame: tp.Any) -> None:
    with state.shutdown_lock:
        state.shutdown_count += 1
        if state.shutdown_count == 1:
            vfx.print_line(f"\n{vm.Colors['dim']}💤 vesta is tired and taking a nap to help remember stuff...{vm.Colors['reset']}")
            if state.shutdown_event:
                state.shutdown_event.set()
        elif state.shutdown_count > 2:
            vfx.print_line(f"\n{vm.Colors['yellow']}⚡ Force shutdown!{vm.Colors['reset']}")
            vfx.exit_process(0)


async def graceful_shutdown(state: vm.State, config: vm.VestaSettings) -> None:
    try:
        await asyncio.wait_for(preserve_memory(state, config), timeout=config.memory_agent_timeout)
    except asyncio.TimeoutError:
        vfx.log_error("Memory preservation timeout", vm.Colors)
    except Exception as e:
        vfx.log_error(f"Memory error: {e}", vm.Colors)

    if state.client:
        try:
            await state.client.__aexit__(None, None, None)
        except Exception:
            pass

    vfx.log_success("sweet dreams!", vm.Colors)


def print_header(config: vm.VestaSettings) -> None:
    vfx.print_line(f"\n{vm.Colors['cyan']}╔{'═' * 58}╗")
    vfx.print_line(f"║{' ' * 23}{vm.Colors['yellow']}🔥 VESTA{vm.Colors['cyan']}{' ' * 27}║")
    vfx.print_line(f"╚{'═' * 58}╝{vm.Colors['reset']}\n")
    if config.mcp_servers:
        vfx.print_line(f"{vm.Colors['dim']}Active MCPs: {', '.join(config.mcp_servers.keys())}{vm.Colors['reset']}\n")


def ensure_memory_file() -> None:
    memory_file = get_root_path() / "MEMORY.md"
    memory_template = get_root_path() / "MEMORY.md.tmp"

    if not memory_file.exists() and memory_template.exists():
        import shutil

        shutil.copy(memory_template, memory_file)
        vfx.log_info("Created MEMORY.md from template", vm.Colors)


async def message_processor(queue: asyncio.Queue, state: vm.State, config: vm.VestaSettings) -> None:
    current_state = state
    if config.debug:
        vfx.log_info("[DEBUG] Message processor started", vm.Colors)

    while current_state.shutdown_event and not current_state.shutdown_event.is_set():
        try:
            msg, is_user = await asyncio.wait_for(queue.get(), timeout=1.0)
            if config.debug:
                vfx.log_info(f"[DEBUG] Processing message from {'user' if is_user else 'system'}: {msg[:100]}", vm.Colors)
            current_state = vu.update_state(current_state, is_processing=True)

            responses, new_state = await process_message_with_typing(msg, current_state, config, is_user)
            current_state = new_state

            for i, response in enumerate(responses):
                if response and response.strip():
                    if i > 0:
                        await vfx.sleep(0.3)
                    output_line(response, current_state)

            current_state = vu.update_state(current_state, is_processing=False)
            if config.debug:
                vfx.log_info("[DEBUG] Message processing completed", vm.Colors)
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            vfx.log_error(f"Queue error: {str(e)[:100]}", vm.Colors)
            import traceback

            if config.debug:
                traceback.print_exc()
            current_state = vu.update_state(current_state, is_processing=False)


async def input_handler(queue: asyncio.Queue, state: vm.State) -> None:
    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            user_msg = await aioconsole.ainput(f"{vm.Colors['green']}>{vm.Colors['reset']} ")
            if state.shutdown_event and state.shutdown_event.is_set():
                break
            if not user_msg.strip():
                continue

            vfx.move_cursor_up_and_clear()
            print_timestamp_message(user_msg, "You")
            await queue.put((user_msg.strip(), True))
        except (KeyboardInterrupt, EOFError):
            if state.shutdown_event:
                state.shutdown_event.set()
            break
        except asyncio.CancelledError:
            break


async def check_whatsapp_bridge() -> None:
    if not is_whatsapp_bridge_running():
        print_timestamp_message("🔄 WhatsApp bridge disconnected, restarting...", "System")
        start_whatsapp_bridge()


async def check_proactive_task(queue: asyncio.Queue, config: vm.VestaSettings) -> None:
    print_timestamp_message("⏰ Running 30-minute check...", "System")
    await queue.put((config.proactive_check_message, False))


async def monitor_loop(queue: asyncio.Queue, state: vm.State, config: vm.VestaSettings) -> None:
    last_proactive = vfx.get_current_time()
    last_bridge_check = vfx.get_current_time()
    current_state = state
    notification_buffer = []
    buffer_start_time = None

    if config.debug:
        vfx.log_info("[DEBUG] Monitor loop started", vm.Colors)

    while current_state.shutdown_event and not current_state.shutdown_event.is_set():
        try:
            if config.debug:
                vfx.log_info(f"[DEBUG] Monitor sleeping for {config.notification_check_interval}s", vm.Colors)
            await vfx.sleep(config.notification_check_interval)
        except asyncio.CancelledError:
            if config.debug:
                vfx.log_info("[DEBUG] Monitor loop cancelled", vm.Colors)
            break
        except Exception as e:
            vfx.log_error(f"Monitor loop sleep error: {e}", vm.Colors)
            continue

        if current_state.shutdown_event and current_state.shutdown_event.is_set():
            break

        now = vfx.get_current_time()
        if config.debug:
            vfx.log_info(f"[DEBUG] Monitor check at {now.strftime('%H:%M:%S')}", vm.Colors)

        actions = vu.calculate_monitoring_actions(now, last_proactive, last_bridge_check, None, config)

        for action in actions:
            if action.action_type == "check_bridge":
                await check_whatsapp_bridge()
                last_bridge_check = now
            elif action.action_type == "check_proactive":
                await check_proactive_task(queue, config)
                last_proactive = now

        try:
            new_notifs = await load_notifications()
            if config.debug and new_notifs:
                vfx.log_info(f"[DEBUG] Found {len(new_notifs)} notification files", vm.Colors)

            if new_notifs:
                existing_paths = {n.file_path for n in notification_buffer}
                truly_new = vu.filter_new_notifications(new_notifs, existing_paths)

                if truly_new:
                    if config.debug:
                        vfx.log_info(f"[DEBUG] {len(truly_new)} new notifications to process", vm.Colors)
                    notification_buffer.extend(truly_new)
                    if buffer_start_time is None:
                        buffer_start_time = now

                    for notif in truly_new:
                        icon, sender, display_msg = notif.get_display_info()
                        print_timestamp_message(f"{icon} {display_msg}", sender)
        except Exception as e:
            vfx.log_error(f"Error loading notifications: {e}", vm.Colors)
            import traceback

            if config.debug:
                traceback.print_exc()

        if vu.should_process_notification_buffer(notification_buffer, buffer_start_time, now, config.notification_buffer_delay):
            try:
                if config.debug:
                    vfx.log_info(f"[DEBUG] Processing {len(notification_buffer)} buffered notifications", vm.Colors)
                new_state = await process_notification_batch(notification_buffer, queue, current_state, config)
                current_state = new_state
                notification_buffer = []
                buffer_start_time = None
            except Exception as e:
                vfx.log_error(f"Error processing notifications: {e}", vm.Colors)
                import traceback

                if config.debug:
                    traceback.print_exc()
                notification_buffer = []
                buffer_start_time = None


async def run_vesta(config: vm.VestaSettings, state: vm.State) -> None:
    state = vu.update_state(state, shutdown_event=asyncio.Event())

    handler = functools.partial(signal_handler, state, config)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    ensure_memory_file()
    print_header(config)
    start_whatsapp_bridge()

    message_queue = asyncio.Queue()

    tasks = [
        asyncio.create_task(input_handler(message_queue, state)),
        asyncio.create_task(message_processor(message_queue, state, config)),
        asyncio.create_task(monitor_loop(message_queue, state, config)),
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
        await asyncio.wait_for(graceful_shutdown(state, config), timeout=config.shutdown_timeout)
    except asyncio.TimeoutError:
        vfx.log_error("Shutdown timeout", vm.Colors)


def check_dependencies() -> None:
    import shutil

    if shutil.which("npm") is None:
        raise RuntimeError("npm is not found in PATH. Please install Node.js and npm: https://nodejs.org/")

    if shutil.which("uv") is None:
        raise RuntimeError("uv is not found in PATH. Please install uv: https://docs.astral.sh/uv/getting-started/installation/")


def main() -> None:
    check_dependencies()

    # Initialize configuration and state
    config = vm.VestaSettings()
    os.environ["MAX_MCP_OUTPUT_TOKENS"] = str(config.max_mcp_output_tokens)
    initial_state = vm.State()

    try:
        asyncio.run(run_vesta(config, initial_state))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        vfx.print_line(f"\n💥 Fatal error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
