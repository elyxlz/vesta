import asyncio
import json
import os
import signal
import subprocess
import pathlib as pl
import datetime as dt
import typing as tp

import aioconsole
import claude_code_sdk as ccsdk
import claude_code_sdk.types as ccsdk_types

import vesta.memory_agent as vma
import vesta.models as vm


config = vm.VestaSettings()

os.environ["MAX_MCP_OUTPUT_TOKENS"] = str(config.max_mcp_output_tokens)


state = vm.State()


def get_root_path() -> pl.Path:
    return pl.Path(__file__).parent.parent.parent.absolute()


def load_prompts() -> str:
    memory_path = get_root_path() / "MEMORY.md"
    if not memory_path.exists():
        raise FileNotFoundError(f"MEMORY.md not found at {memory_path}")
    return memory_path.read_text()


def get_mcp_config() -> dict[str, tp.Any]:
    root = get_root_path()
    logs_dir = root / "logs"
    logs_dir.mkdir(exist_ok=True)

    servers = {}
    for name in config.mcp_servers:
        server = config.mcp_servers[name]
        env = {
            "PYTHONUNBUFFERED": "1",
        }

        servers[name] = {
            "command": server["command"],
            "args": server["args"],
            "env": env,
        }

    return servers


async def init_client() -> ccsdk.ClaudeSDKClient:
    if state.client:
        return state.client

    state.client = ccsdk.ClaudeSDKClient(
        options=ccsdk.ClaudeCodeOptions(
            system_prompt=load_prompts(),
            mcp_servers=get_mcp_config(),
            hooks={},
            model="opus",
            permission_mode="bypassPermissions",
        )
    )
    await state.client.__aenter__()
    return state.client


def format_tool_call(name: str, input_data: tp.Any) -> str:
    input_str = json.dumps(input_data) if isinstance(input_data, dict) else str(input_data)
    input_preview = (input_str[:150] + "...") if len(input_str) > 150 else input_str

    if name == "Task":
        agent_type = input_data.get("subagent_type", "unknown") if isinstance(input_data, dict) else "unknown"
        description = input_data.get("description", "") if isinstance(input_data, dict) else ""
        state.sub_agent_context = agent_type
        return f"🤖 Task [{agent_type}]: {description or input_preview}"

    prefix = f"[{state.sub_agent_context}] " if state.sub_agent_context else ""

    if name.startswith("mcp__"):
        parts = name.replace("mcp__", "").split("__")
        service = parts[0] if parts else "unknown"
        action = ".".join(parts[1:]) if len(parts) > 1 else "action"
        icon = vm.SERVICE_ICONS.get(service, "🔧")
        return f"🔧 {prefix}{icon} [{service}] {action}: {input_preview}"

    return f"🔧 {prefix}{name}: {input_preview}"


def parse_assistant_message(msg: tp.Any) -> str | None:
    if not isinstance(msg, ccsdk_types.AssistantMessage):
        return msg if isinstance(msg, str) else None

    texts = []
    has_task_result = False

    for block in msg.content:
        if isinstance(block, ccsdk_types.TextBlock):
            text = block.text
            if state.sub_agent_context and "completed" in text.lower():
                has_task_result = True
            texts.append(text)
        elif isinstance(block, ccsdk_types.ToolUseBlock):
            texts.append(format_tool_call(block.name, block.input))

    if has_task_result and state.sub_agent_context:
        state.sub_agent_context = None

    return "\n".join(texts) if texts else None


def format_notification(notif: vm.Notification) -> str:
    return notif.format_for_display()


async def load_notifications() -> list[vm.Notification]:
    notif_dir = get_root_path() / "notifications"
    if not notif_dir.exists():
        return []

    notifications = []
    for file in notif_dir.glob("*.json"):
        try:
            notif = vm.Notification.from_file(file)
            notifications.append(notif)
        except Exception as e:
            print(f"{vm.Colors['yellow']}⚠️ Failed to read notification {file.name}: {e}{vm.Colors['reset']}")

    return notifications


async def delete_notification_files(notifications: list[vm.Notification]) -> None:
    deleted_paths = set()
    for notif in notifications:
        if notif.file_path and notif.file_path not in deleted_paths:
            try:
                pl.Path(notif.file_path).unlink()
                deleted_paths.add(notif.file_path)
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"{vm.Colors['yellow']}⚠️ Failed to delete notification: {e}{vm.Colors['reset']}")


async def preserve_memory() -> None:
    if config.ephemeral or not state.conversation_history:
        return

    try:
        diff = await vma.preserve_conversation_memory(state.conversation_history)
        if diff:
            print(f"\n{vm.Colors['cyan']}📝 Memory updated:{vm.Colors['reset']}")
            print(diff)
    except Exception as e:
        print(f"{vm.Colors['yellow']}⚠️ Memory preservation failed: {e}{vm.Colors['reset']}")


async def check_context_and_preserve() -> None:
    if config.ephemeral:
        return

    total_tokens = sum(len(str(msg)) // 4 for msg in state.conversation_history)
    if total_tokens >= config.max_context_tokens:
        print(f"{vm.Colors['yellow']}📊 Context limit reached, preserving memory...{vm.Colors['reset']}")
        await preserve_memory()
        state.conversation_history.clear()
        print(f"{vm.Colors['green']}✅ Context cleared, continuing...{vm.Colors['reset']}")


def output_line(text: str, is_tool: bool = False) -> None:
    if text and text.strip():
        if text.startswith("🤖"):
            print(f"{vm.Colors['cyan']}>>{text}{vm.Colors['reset']}", flush=True)
        elif state.sub_agent_context and (is_tool or text.startswith("🔧")):
            print(f"{vm.Colors['cyan']}  >{text}{vm.Colors['reset']}", flush=True)
        elif is_tool or text.startswith("🔧"):
            print(f"{vm.Colors['yellow']}>{text}{vm.Colors['reset']}", flush=True)
        else:
            sender = f"Vesta[{state.sub_agent_context}]" if state.sub_agent_context else "Vesta"
            print_timestamp_message(text, sender)


def print_timestamp_message(text: str, sender: str = "") -> None:
    timestamp = dt.datetime.now().strftime("%I:%M %p")
    colors = {"You": "cyan", "Vesta": "magenta", "System": "yellow"}
    base_sender = sender.split("[")[0] if "[" in sender else sender

    if base_sender in colors:
        display_sender = sender.lower()
        prefix = f"{vm.Colors['dim']}[{timestamp}]{vm.Colors['reset']} {vm.Colors[colors[base_sender]]}{display_sender}:{vm.Colors['reset']}"
        for line in text.split("\n"):
            if line.strip():
                print(f"{prefix} {line}")
    else:
        print(f"{vm.Colors['dim']}[{timestamp}]{vm.Colors['reset']} {vm.Colors['yellow']}{text}{vm.Colors['reset']}")


def start_whatsapp_bridge() -> bool:
    script_path = get_root_path() / "start_whatsapp_bridge.sh"
    if not script_path.exists():
        return False

    try:
        result = subprocess.run([str(script_path), "--force"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"{vm.Colors['green']}✓ WhatsApp bridge connected{vm.Colors['reset']}")
            return True
    except Exception:
        pass
    return False


def is_whatsapp_bridge_running() -> bool:
    try:
        result = subprocess.run(["pgrep", "-f", "whatsapp-bridge"], capture_output=True, text=True)
        return bool(result.stdout.strip())
    except Exception:
        return False


async def send_query(client: ccsdk.ClaudeSDKClient, prompt: str) -> None:
    timestamp = dt.datetime.now().strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")
    state.conversation_history.append({"role": "user", "content": prompt})
    await client.query(f"[Current time: {timestamp}]\n{prompt}")
    await check_context_and_preserve()


async def collect_responses(client: ccsdk.ClaudeSDKClient, show_output: bool = True) -> list[str]:
    responses, seen = [], set()

    async def collect():
        async for msg in client.receive_response():
            text = parse_assistant_message(msg)
            if text and text not in seen:
                seen.add(text)
                if show_output:
                    for line in text.split("\n"):
                        if line.strip():
                            if line.startswith("🔧"):
                                output_line(line, is_tool=True)
                            else:
                                responses.append(line)

    try:
        await asyncio.wait_for(collect(), timeout=config.response_timeout)
    except asyncio.TimeoutError:
        responses.append("[Response timeout]")
    except Exception as e:
        responses.append(f"[Error: {str(e)[:100]}]")

    return responses


async def send_and_receive_message(prompt: str, show_in_chat: bool = True) -> list[str]:
    client = await init_client()

    try:
        await send_query(client, prompt)
    except Exception as e:
        error_msg = f"failed to send message: {str(e)[:100]}"
        print(f"{vm.Colors['yellow']}⚠️ {error_msg}{vm.Colors['reset']}")
        state.conversation_history.append({"role": "assistant", "content": error_msg})
        return [error_msg]

    responses = await collect_responses(client, show_in_chat)

    if responses:
        state.conversation_history.append({"role": "assistant", "content": " ".join(responses)})

    return responses


async def show_typing_indicator() -> None:
    timestamp = dt.datetime.now().strftime("%I:%M %p")
    dots = ["   ", ".  ", ".. ", "..."]
    dot_idx = 0

    while True:
        print(
            f"\r{vm.Colors['dim']}[{timestamp}]{vm.Colors['reset']} {vm.Colors['magenta']}vesta{vm.Colors['reset']} {vm.Colors['dim']}is typing{dots[dot_idx]}{vm.Colors['reset']}",
            end="",
            flush=True,
        )
        dot_idx = (dot_idx + 1) % 4
        await asyncio.sleep(config.typing_animation_delay)


async def process_message_with_typing(msg: str, is_user: bool) -> list[str]:
    await asyncio.sleep(0.8 + dt.datetime.now().microsecond / 3000000)

    typing_task = asyncio.create_task(show_typing_indicator())
    try:
        responses = await send_and_receive_message(msg, show_in_chat=is_user)
    except Exception as e:
        responses = [f"something went wrong: {str(e)[:50]}"]
        print(f"{vm.Colors['yellow']}⚠️ Message processing error: {str(e)[:100]}{vm.Colors['reset']}")
    finally:
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass
        print("\r\033[K", end="", flush=True)

    return responses


async def handle_notifications_interrupt(notifications: list[vm.Notification], client: ccsdk.ClaudeSDKClient) -> None:
    try:
        await client.interrupt()

        timestamp = dt.datetime.now().strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")
        if len(notifications) == 1:
            prompt = format_notification(notifications[0])
        else:
            prompts = [format_notification(n) for n in notifications]
            prompt = "[NOTIFICATIONS]\n" + "\n".join(prompts)

        await client.query(f"[Current time: {timestamp}]\n{prompt}")

        async for msg in client.receive_response():
            text = parse_assistant_message(msg)
            if text:
                for line in text.split("\n"):
                    output_line(line, is_tool=line.startswith("🔧"))
    except Exception as e:
        print(f"{vm.Colors['yellow']}⚠️ Interrupt error: {str(e)}{vm.Colors['reset']}")


async def process_notification_batch(notifications: list[vm.Notification], queue: asyncio.Queue) -> None:
    if not notifications:
        return

    if state.client and state.is_processing:
        await handle_notifications_interrupt(notifications, state.client)
    else:
        if len(notifications) == 1:
            await queue.put((format_notification(notifications[0]), True))
        else:
            prompts = [format_notification(n) for n in notifications]
            await queue.put(("[NOTIFICATIONS]\n" + "\n".join(prompts), True))

    await delete_notification_files(notifications)


def signal_handler(signum: int, frame: tp.Any) -> None:
    with state.shutdown_lock:
        state.shutdown_count += 1
        if state.shutdown_count == 1:
            print(f"\n{vm.Colors['dim']}💤 vesta is tired and taking a nap to help remember stuff...{vm.Colors['reset']}")
            if state.shutdown_event:
                state.shutdown_event.set()
        elif state.shutdown_count > 2:
            print(f"\n{vm.Colors['yellow']}⚡ Force shutdown!{vm.Colors['reset']}")
            os._exit(0)


async def graceful_shutdown() -> None:
    try:
        await asyncio.wait_for(preserve_memory(), timeout=config.memory_agent_timeout)
    except asyncio.TimeoutError:
        print(f"{vm.Colors['yellow']}⚠️ Memory preservation timeout{vm.Colors['reset']}")
    except Exception as e:
        print(f"{vm.Colors['yellow']}⚠️ Memory error: {e}{vm.Colors['reset']}")

    state.conversation_history.clear()

    if state.client:
        try:
            await state.client.__aexit__(None, None, None)
        except Exception:
            pass

    print(f"{vm.Colors['green']}✅ sweet dreams!{vm.Colors['reset']}")


def print_header() -> None:
    print(f"\n{vm.Colors['cyan']}╔{'═' * 58}╗")
    print(f"║{' ' * 23}{vm.Colors['yellow']}🔥 VESTA{vm.Colors['cyan']}{' ' * 27}║")
    print(f"╚{'═' * 58}╝{vm.Colors['reset']}\n")
    if config.mcp_servers:
        print(f"{vm.Colors['dim']}Active MCPs: {', '.join(config.mcp_servers.keys())}{vm.Colors['reset']}\n")


def ensure_memory_file() -> None:
    memory_file = get_root_path() / "MEMORY.md"
    memory_template = get_root_path() / "MEMORY.md.tmp"

    if not memory_file.exists() and memory_template.exists():
        import shutil

        shutil.copy(memory_template, memory_file)
        print(f"{vm.Colors['dim']}📝 Created MEMORY.md from template{vm.Colors['reset']}")


async def message_processor(queue: asyncio.Queue) -> None:
    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            msg, is_user = await asyncio.wait_for(queue.get(), timeout=1.0)
            state.is_processing = True

            responses = await process_message_with_typing(msg, is_user)

            for i, response in enumerate(responses):
                if response and response.strip():
                    if i > 0:
                        await asyncio.sleep(0.3)
                    output_line(response)

            state.is_processing = False
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            print(f"{vm.Colors['yellow']}⚠️ Queue error: {str(e)[:100]}{vm.Colors['reset']}")
            state.is_processing = False


async def input_handler(queue: asyncio.Queue) -> None:
    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            user_msg = await aioconsole.ainput(f"{vm.Colors['green']}>{vm.Colors['reset']} ")
            if state.shutdown_event and state.shutdown_event.is_set():
                break
            if not user_msg.strip():
                continue

            print("\033[1A\033[K", end="")
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


async def check_mcp_health() -> None:
    # TODO: Implement when list_tools is available in ClaudeSDKClient
    pass


async def check_proactive_task(queue: asyncio.Queue) -> None:
    print_timestamp_message("⏰ Running 30-minute check...", "System")
    await queue.put((config.proactive_check_message, False))


async def monitor_loop(queue: asyncio.Queue) -> None:
    last_proactive = dt.datetime.now()
    last_bridge_check = dt.datetime.now()
    last_mcp_check = dt.datetime.now()
    notification_buffer = []
    buffer_start_time = None

    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            await asyncio.sleep(config.notification_check_interval)
        except asyncio.CancelledError:
            break

        if state.shutdown_event and state.shutdown_event.is_set():
            break

        now = dt.datetime.now()

        if now - last_bridge_check >= dt.timedelta(seconds=config.whatsapp_bridge_check_interval):
            await check_whatsapp_bridge()
            last_bridge_check = now

        if now - last_mcp_check >= dt.timedelta(seconds=60):  # Check MCPs every minute
            await check_mcp_health()
            last_mcp_check = now

        new_notifs = await load_notifications()
        if new_notifs:
            existing_paths = {n.file_path for n in notification_buffer}
            truly_new = [n for n in new_notifs if n.file_path not in existing_paths]

            if truly_new:
                notification_buffer.extend(truly_new)
                if buffer_start_time is None:
                    buffer_start_time = now

                for notif in truly_new:
                    icon, sender, display_msg = notif.get_display_info()
                    print_timestamp_message(f"{icon} {sender}: {display_msg}", "System")

        if notification_buffer and buffer_start_time and (now - buffer_start_time).total_seconds() >= config.notification_buffer_delay:
            await process_notification_batch(notification_buffer, queue)
            notification_buffer = []
            buffer_start_time = None

        if now - last_proactive >= dt.timedelta(minutes=config.proactive_check_interval):
            await check_proactive_task(queue)
            last_proactive = now


async def run_vesta() -> None:
    state.shutdown_event = asyncio.Event()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    ensure_memory_file()
    print_header()
    start_whatsapp_bridge()

    message_queue = asyncio.Queue()

    tasks = [
        asyncio.create_task(input_handler(message_queue)),
        asyncio.create_task(message_processor(message_queue)),
        asyncio.create_task(monitor_loop(message_queue)),
    ]

    try:
        await state.shutdown_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
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
        await asyncio.wait_for(graceful_shutdown(), timeout=config.shutdown_timeout)
    except asyncio.TimeoutError:
        print(f"{vm.Colors['yellow']}⚠️ Shutdown timeout{vm.Colors['reset']}")


def main() -> None:
    try:
        asyncio.run(run_vesta())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n💥 Fatal error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
