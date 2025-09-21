import asyncio
import json
import os
import signal
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple

import aioconsole
from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions
from claude_code_sdk.types import (
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
)

from .memory_agent import preserve_conversation_memory


@dataclass(frozen=True)
class ConfigClass:
    EPHEMERAL_MODE: bool = os.environ.get("EPHEMERAL", "").lower() == "true"
    MAX_MCP_OUTPUT_TOKENS: str = os.environ.get("MAX_MCP_OUTPUT_TOKENS", "200000")
    NOTIFICATION_CHECK_INTERVAL: int = 2
    NOTIFICATION_BUFFER_DELAY: int = 3
    PROACTIVE_CHECK_INTERVAL: int = 30
    WHATSAPP_BRIDGE_CHECK_INTERVAL: int = 30
    RESPONSE_TIMEOUT: int = 60
    MEMORY_AGENT_TIMEOUT: int = 1200  # 20 minutes for memory agent
    TYPING_ANIMATION_DELAY: float = 0.5
    SHUTDOWN_TIMEOUT: int = 310
    TASK_GATHER_TIMEOUT: int = 2
    MAX_CONTEXT_TOKENS: int = 180000


Config = ConfigClass()

os.environ["MAX_MCP_OUTPUT_TOKENS"] = Config.MAX_MCP_OUTPUT_TOKENS

C = {
    "dim": "\033[2m",
    "cyan": "\033[96m",
    "magenta": "\033[95m",
    "yellow": "\033[93m",
    "green": "\033[92m",
    "reset": "\033[0m",
}

SERVICE_ICONS = {
    "playwright": "🌐",
    "whatsapp": "📱",
    "scheduler": "⏰",
    "microsoft": "📧",
}


def get_mcp_servers():
    root = Path(__file__).parent.parent.parent.absolute()
    return {
        "microsoft": {
            "command": "uv",
            "args": [
                "run",
                "--directory",
                "mcps/microsoft-mcp",
                "microsoft-mcp",
                "--data-dir",
                str(root / "data/microsoft-mcp"),
                "--notifications-dir",
                str(root / "notifications"),
            ],
        },
        "whatsapp": {
            "command": "uv",
            "args": [
                "run",
                "--directory",
                "mcps/whatsapp-mcp/whatsapp-mcp-server",
                "main.py",
                "--data-dir",
                str(root / "data/whatsapp-mcp"),
            ],
        },
        "scheduler": {
            "command": "uv",
            "args": [
                "run",
                "--directory",
                "mcps/scheduler-mcp",
                "scheduler-mcp",
                "--data-dir",
                str(root / "data/scheduler-mcp"),
                "--notifications-dir",
                str(root / "notifications"),
            ],
        },
        "playwright": {
            "command": "npx",
            "args": [
                "--prefix",
                "mcps/playwright-mcp",
                "mcp-server-playwright",
                "--browser",
                "chromium",
                "--blocked-origins",
                "googleads.g.doubleclick.net;googlesyndication.com",
                "--output-dir",
                str(root / "data/playwright-mcp/screenshots"),
                "--image-responses",
                "omit",
            ],
        },
    }


MCP_SERVERS = get_mcp_servers()


@dataclass
class State:
    client: Optional[ClaudeSDKClient] = None
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    shutdown_event: Optional[asyncio.Event] = None
    shutdown_lock: threading.Lock = field(default_factory=threading.Lock)
    shutdown_count: int = 0
    is_processing: bool = False
    sub_agent_context: Optional[str] = None


state = State()


def get_root_path() -> Path:
    return Path(__file__).parent.parent.parent.absolute()


def load_prompts() -> str:
    memory_path = get_root_path() / "MEMORY.md"
    if not memory_path.exists():
        raise FileNotFoundError(f"MEMORY.md not found at {memory_path}")
    return memory_path.read_text()


def get_mcp_config() -> Dict[str, Any]:
    root = get_root_path()
    logs_dir = root / "logs"
    logs_dir.mkdir(exist_ok=True)

    config = {}
    for name, server in MCP_SERVERS.items():
        env = {
            "PYTHONUNBUFFERED": "1",
        }

        if name == "playwright":
            env["NODE_PATH"] = str(root / "mcps" / "playwright-mcp" / "node_modules")

        config[name] = {
            "command": server["command"],
            "args": server["args"],
            "env": env,
        }

    return config


async def init_client() -> ClaudeSDKClient:
    if state.client:
        return state.client

    state.client = ClaudeSDKClient(
        options=ClaudeCodeOptions(
            system_prompt=load_prompts(),
            mcp_servers=get_mcp_config(),
            hooks={},
            model="opus",
            permission_mode="bypassPermissions",
            continue_conversation=True
        )
    )
    await state.client.__aenter__()
    return state.client


def format_tool_call(name: str, input_data: Any) -> str:
    input_str = (
        json.dumps(input_data) if isinstance(input_data, dict) else str(input_data)
    )
    input_preview = (input_str[:150] + "...") if len(input_str) > 150 else input_str

    if name == "Task":
        agent_type = (
            input_data.get("subagent_type", "unknown")
            if isinstance(input_data, dict)
            else "unknown"
        )
        description = (
            input_data.get("description", "") if isinstance(input_data, dict) else ""
        )
        state.sub_agent_context = agent_type
        return f"🤖 Task [{agent_type}]: {description or input_preview}"

    prefix = f"[{state.sub_agent_context}] " if state.sub_agent_context else ""

    if name.startswith("mcp__"):
        parts = name.replace("mcp__", "").split("__")
        service = parts[0] if parts else "unknown"
        action = ".".join(parts[1:]) if len(parts) > 1 else "action"
        icon = SERVICE_ICONS.get(service, "🔧")
        return f"🔧 {prefix}{icon} [{service}] {action}: {input_preview}"

    return f"🔧 {prefix}{name}: {input_preview}"


def parse_assistant_message(msg: Any) -> Optional[str]:
    if not isinstance(msg, AssistantMessage):
        return msg if isinstance(msg, str) else None

    texts = []
    has_task_result = False

    for block in msg.content:
        if isinstance(block, TextBlock):
            text = block.text
            if state.sub_agent_context and "completed" in text.lower():
                has_task_result = True
            texts.append(text)
        elif isinstance(block, ToolUseBlock):
            texts.append(format_tool_call(block.name, block.input))

    if has_task_result and state.sub_agent_context:
        state.sub_agent_context = None

    return "\n".join(texts) if texts else None


def format_notification(notif: Dict[str, Any]) -> str:
    meta = notif.get("metadata", {})
    meta_str = (
        f" (metadata: {', '.join(f'{k}={v}' for k, v in meta.items() if v)})"
        if meta
        else ""
    )
    return f"[{notif['type']} from {notif['source']}]{meta_str}: {notif['message']}"


def get_notification_display_info(notif: Dict[str, Any]) -> Tuple[str, str, str]:
    meta = notif.get("metadata", {})
    sender = meta.get("chat_name", meta.get("sender", notif["source"]))
    icon = SERVICE_ICONS.get(notif["source"], "🔔")
    msg = notif["message"]
    display_msg = msg[:200] + "..." if len(msg) > 200 else msg
    return icon, sender, display_msg


async def load_notifications() -> List[Dict[str, Any]]:
    notif_dir = get_root_path() / "notifications"
    if not notif_dir.exists():
        return []

    notifications = []
    for file in notif_dir.glob("*.json"):
        try:
            data = json.loads(file.read_text())
            data["_file_path"] = str(file)
            notifications.append(data)
        except Exception as e:
            print(
                f"{C['yellow']}⚠️ Failed to read notification {file.name}: {e}{C['reset']}"
            )

    return notifications


async def delete_notification_files(notifications: List[Dict[str, Any]]) -> None:
    deleted_paths = set()
    for notif in notifications:
        file_path = notif.get("_file_path")
        if file_path and file_path not in deleted_paths:
            try:
                Path(file_path).unlink()
                deleted_paths.add(file_path)
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"{C['yellow']}⚠️ Failed to delete notification: {e}{C['reset']}")


async def preserve_memory() -> None:
    if Config.EPHEMERAL_MODE or not state.conversation_history:
        return

    try:
        diff = await preserve_conversation_memory(state.conversation_history)
        if diff:
            print(f"\n{C['cyan']}📝 Memory updated:{C['reset']}")
            print(diff)
    except Exception as e:
        print(f"{C['yellow']}⚠️ Memory preservation failed: {e}{C['reset']}")


async def check_context_and_preserve() -> None:
    if Config.EPHEMERAL_MODE:
        return

    total_tokens = sum(len(str(msg)) // 4 for msg in state.conversation_history)
    if total_tokens >= Config.MAX_CONTEXT_TOKENS:
        print(
            f"{C['yellow']}📊 Context limit reached, preserving memory...{C['reset']}"
        )
        await preserve_memory()
        state.conversation_history.clear()
        print(f"{C['green']}✅ Context cleared, continuing...{C['reset']}")


def output_line(text: str, is_tool: bool = False) -> None:
    if text and text.strip():
        if text.startswith("🤖"):
            print(f"{C['cyan']}>>{text}{C['reset']}", flush=True)
        elif state.sub_agent_context and (is_tool or text.startswith("🔧")):
            print(f"{C['cyan']}  >{text}{C['reset']}", flush=True)
        elif is_tool or text.startswith("🔧"):
            print(f"{C['yellow']}>{text}{C['reset']}", flush=True)
        else:
            sender = (
                f"Vesta[{state.sub_agent_context}]"
                if state.sub_agent_context
                else "Vesta"
            )
            print_timestamp_message(text, sender)


def print_timestamp_message(text: str, sender: str = "") -> None:
    timestamp = datetime.now().strftime("%I:%M %p")
    colors = {"You": "cyan", "Vesta": "magenta", "System": "yellow"}
    base_sender = sender.split("[")[0] if "[" in sender else sender

    if base_sender in colors:
        display_sender = sender.lower()
        prefix = f"{C['dim']}[{timestamp}]{C['reset']} {C[colors[base_sender]]}{display_sender}:{C['reset']}"
        for line in text.split("\n"):
            if line.strip():
                print(f"{prefix} {line}")
    else:
        print(f"{C['dim']}[{timestamp}]{C['reset']} {C['yellow']}{text}{C['reset']}")


def start_whatsapp_bridge() -> bool:
    script_path = get_root_path() / "start_whatsapp_bridge.sh"
    if not script_path.exists():
        return False

    try:
        result = subprocess.run(
            [str(script_path), "--force"], capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"{C['green']}✓ WhatsApp bridge connected{C['reset']}")
            return True
    except Exception:
        pass
    return False


def is_whatsapp_bridge_running() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "whatsapp-bridge"], capture_output=True, text=True
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


async def send_query(client: ClaudeSDKClient, prompt: str) -> None:
    timestamp = datetime.now().strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")
    state.conversation_history.append({"role": "user", "content": prompt})
    await client.query(f"[Current time: {timestamp}]\n{prompt}")
    await check_context_and_preserve()


async def collect_responses(
    client: ClaudeSDKClient, show_output: bool = True
) -> List[str]:
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
        await asyncio.wait_for(collect(), timeout=Config.RESPONSE_TIMEOUT)
    except asyncio.TimeoutError:
        responses.append("[Response timeout]")
    except Exception as e:
        responses.append(f"[Error: {str(e)[:100]}]")

    return responses


async def send_and_receive_message(prompt: str, show_in_chat: bool = True) -> List[str]:
    client = await init_client()

    try:
        await send_query(client, prompt)
    except Exception as e:
        error_msg = f"failed to send message: {str(e)[:100]}"
        print(f"{C['yellow']}⚠️ {error_msg}{C['reset']}")
        state.conversation_history.append({"role": "assistant", "content": error_msg})
        return [error_msg]

    responses = await collect_responses(client, show_in_chat)

    if responses:
        state.conversation_history.append(
            {"role": "assistant", "content": " ".join(responses)}
        )

    return responses


async def show_typing_indicator() -> None:
    timestamp = datetime.now().strftime("%I:%M %p")
    dots = ["   ", ".  ", ".. ", "..."]
    dot_idx = 0

    while True:
        print(
            f"\r{C['dim']}[{timestamp}]{C['reset']} {C['magenta']}vesta{C['reset']} "
            f"{C['dim']}is typing{dots[dot_idx]}{C['reset']}",
            end="",
            flush=True,
        )
        dot_idx = (dot_idx + 1) % 4
        await asyncio.sleep(Config.TYPING_ANIMATION_DELAY)


async def process_message_with_typing(msg: str, is_user: bool) -> List[str]:
    await asyncio.sleep(0.8 + datetime.now().microsecond / 3000000)

    typing_task = asyncio.create_task(show_typing_indicator())
    try:
        responses = await send_and_receive_message(msg, show_in_chat=is_user)
    except Exception as e:
        responses = [f"something went wrong: {str(e)[:50]}"]
        print(f"{C['yellow']}⚠️ Message processing error: {str(e)[:100]}{C['reset']}")
    finally:
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass
        print("\r\033[K", end="", flush=True)

    return responses


async def handle_notifications_interrupt(
    notifications: List[Dict[str, Any]], client: ClaudeSDKClient
) -> None:
    try:
        await client.interrupt()

        timestamp = datetime.now().strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")
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
        print(f"{C['yellow']}⚠️ Interrupt error: {str(e)}{C['reset']}")


async def process_notification_batch(
    notifications: List[Dict[str, Any]], queue: asyncio.Queue
) -> None:
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


def signal_handler(signum: int, frame: Any) -> None:
    with state.shutdown_lock:
        state.shutdown_count += 1
        if state.shutdown_count == 1:
            print(
                f"\n{C['dim']}💤 vesta is tired and taking a nap to help remember stuff...{C['reset']}"
            )
            if state.shutdown_event:
                state.shutdown_event.set()
        elif state.shutdown_count > 2:
            print(f"\n{C['yellow']}⚡ Force shutdown!{C['reset']}")
            os._exit(0)


async def graceful_shutdown() -> None:
    try:
        await asyncio.wait_for(preserve_memory(), timeout=Config.MEMORY_AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        print(f"{C['yellow']}⚠️ Memory preservation timeout{C['reset']}")
    except Exception as e:
        print(f"{C['yellow']}⚠️ Memory error: {e}{C['reset']}")

    state.conversation_history.clear()

    if state.client:
        try:
            await state.client.__aexit__(None, None, None)
        except Exception:
            pass

    print(f"{C['green']}✅ sweet dreams!{C['reset']}")


def print_header() -> None:
    print(f"\n{C['cyan']}╔{'═' * 58}╗")
    print(f"║{' ' * 23}{C['yellow']}🔥 VESTA{C['cyan']}{' ' * 27}║")
    print(f"╚{'═' * 58}╝{C['reset']}\n")
    if MCP_SERVERS:
        print(f"{C['dim']}Active MCPs: {', '.join(MCP_SERVERS.keys())}{C['reset']}\n")


def ensure_memory_file() -> None:
    memory_file = get_root_path() / "MEMORY.md"
    memory_template = get_root_path() / "MEMORY.md.tmp"

    if not memory_file.exists() and memory_template.exists():
        import shutil

        shutil.copy(memory_template, memory_file)
        print(f"{C['dim']}📝 Created MEMORY.md from template{C['reset']}")


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
            print(f"{C['yellow']}⚠️ Queue error: {str(e)[:100]}{C['reset']}")
            state.is_processing = False


async def input_handler(queue: asyncio.Queue) -> None:
    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            user_msg = await aioconsole.ainput(f"{C['green']}>{C['reset']} ")
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
        print_timestamp_message(
            "🔄 WhatsApp bridge disconnected, restarting...", "System"
        )
        start_whatsapp_bridge()


async def check_mcp_health() -> None:
    if not state.client:
        return
    try:
        tools = [t.name for t in await state.client.list_tools()]
        for mcp in MCP_SERVERS:
            if not any(t.startswith(f"mcp__{mcp}__") for t in tools):
                print_timestamp_message(
                    f"⚠️ {SERVICE_ICONS.get(mcp, '🔧')} MCP '{mcp}' disconnected!",
                    "System",
                )
    except Exception:
        pass


async def collect_new_notifications(
    existing_buffer: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    new_notifs = await load_notifications()
    if not new_notifs:
        return []

    existing_paths = {n.get("_file_path") for n in existing_buffer}
    truly_new = [n for n in new_notifs if n.get("_file_path") not in existing_paths]

    for notif in truly_new:
        icon, sender, display_msg = get_notification_display_info(notif)
        print_timestamp_message(f"{icon} {sender}: {display_msg}", "System")

    return truly_new


async def check_proactive_task(queue: asyncio.Queue) -> None:
    print_timestamp_message("⏰ Running 30-minute check...", "System")
    await queue.put(
        (
            "It's been 30 minutes. Is there anything useful you could do right now?",
            False,
        )
    )


async def monitor_loop(queue: asyncio.Queue) -> None:
    last_proactive = datetime.now()
    last_bridge_check = datetime.now()
    last_mcp_check = datetime.now()
    notification_buffer = []
    buffer_start_time = None

    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            await asyncio.sleep(Config.NOTIFICATION_CHECK_INTERVAL)
        except asyncio.CancelledError:
            break

        if state.shutdown_event and state.shutdown_event.is_set():
            break

        now = datetime.now()

        if now - last_bridge_check >= timedelta(
            seconds=Config.WHATSAPP_BRIDGE_CHECK_INTERVAL
        ):
            await check_whatsapp_bridge()
            last_bridge_check = now

        if now - last_mcp_check >= timedelta(seconds=60):  # Check MCPs every minute
            await check_mcp_health()
            last_mcp_check = now

        new_notifs = await load_notifications()
        if new_notifs:
            existing_paths = {n.get("_file_path") for n in notification_buffer}
            truly_new = [
                n for n in new_notifs if n.get("_file_path") not in existing_paths
            ]

            if truly_new:
                notification_buffer.extend(truly_new)
                if buffer_start_time is None:
                    buffer_start_time = now

                for notif in truly_new:
                    icon, sender, display_msg = get_notification_display_info(notif)
                    print_timestamp_message(f"{icon} {sender}: {display_msg}", "System")

        if (
            notification_buffer
            and buffer_start_time
            and (now - buffer_start_time).total_seconds()
            >= Config.NOTIFICATION_BUFFER_DELAY
        ):
            await process_notification_batch(notification_buffer, queue)
            notification_buffer = []
            buffer_start_time = None

        if now - last_proactive >= timedelta(minutes=Config.PROACTIVE_CHECK_INTERVAL):
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
            timeout=Config.TASK_GATHER_TIMEOUT,
        )
    except asyncio.TimeoutError:
        pass

    try:
        await asyncio.wait_for(graceful_shutdown(), timeout=Config.SHUTDOWN_TIMEOUT)
    except asyncio.TimeoutError:
        print(f"{C['yellow']}⚠️ Shutdown timeout{C['reset']}")


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
