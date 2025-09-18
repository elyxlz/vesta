import asyncio
import json
import os
import signal
import subprocess
import threading
from pathlib import Path
from datetime import datetime, timedelta

import aioconsole
from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions
from claude_code_sdk.types import (
    McpStdioServerConfig,
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
)

from .memory_agent import preserve_conversation_memory

ephemeral_mode = os.environ.get("EPHEMERAL", "").lower() == "true"
MCP_SERVERS = {
    "microsoft": {
        "command": "uv",
        "args": ["run", "--directory", "mcps/microsoft-mcp", "microsoft-mcp"],
    },
    "whatsapp": {
        "command": "uv",
        "args": [
            "run",
            "--directory",
            "mcps/whatsapp-mcp/whatsapp-mcp-server",
            "main.py",
        ],
    },
    "scheduler": {
        "command": "uv",
        "args": ["run", "--directory", "mcps/scheduler-mcp", "scheduler-mcp"],
    },
}
NOTIFICATION_CHECK_INTERVAL = 2
PROACTIVE_CHECK_INTERVAL = 30
MAX_CONTEXT_TOKENS = 180000
CONTEXT_SIZE_THRESHOLD = 0.9

C = {
    "dim": "\033[2m",
    "cyan": "\033[96m",
    "magenta": "\033[95m",
    "yellow": "\033[93m",
    "green": "\033[92m",
    "reset": "\033[0m",
}

CLIENT = None
CONVERSATION_HISTORY = []
SHUTDOWN_EVENT: asyncio.Event | None = None
shutdown_lock = threading.Lock()
shutdown_count = 0
IS_PROCESSING = False


def load_prompts():
    memory_path = Path(__file__).parent.parent.parent / "MEMORY.md"
    if not memory_path.exists():
        raise FileNotFoundError(f"MEMORY.md not found at {memory_path}")
    return memory_path.read_text()


def get_mcp_config():
    root = Path(__file__).parent.parent.parent.absolute()
    return {
        name: McpStdioServerConfig(
            command=s["command"],
            args=s["args"],
            env={
                "PYTHONUNBUFFERED": "1",
                "NOTIFICATIONS_DIR": str(root / "notifications"),
                "DATA_DIR": str(root / "data"),
            },
        )
        for name, s in MCP_SERVERS.items()
    }


async def process_notifications():
    notif_dir = Path(__file__).parent.parent.parent / "notifications"
    if not notif_dir.exists():
        return []

    notifications = []
    for file in notif_dir.glob("*.json"):
        try:
            notifications.append(json.loads(file.read_text()))
            file.unlink()
        except Exception:
            pass
    return notifications


async def init_client():
    global CLIENT
    if CLIENT:
        return CLIENT

    CLIENT = ClaudeSDKClient(
        options=ClaudeCodeOptions(
            system_prompt=load_prompts(),
            mcp_servers=get_mcp_config(),
            hooks={},
            model="claude-opus-4-1-20250805",  # Using latest Opus 4.1 model
            permission_mode="bypassPermissions",
        )
    )
    await CLIENT.__aenter__()
    return CLIENT


def parse_message(msg):
    if isinstance(msg, AssistantMessage):
        texts = []
        for block in msg.content:
            if isinstance(block, TextBlock):
                texts.append(block.text)
            elif isinstance(block, ToolUseBlock):
                tool_name = block.name
                tool_input = (
                    json.dumps(block.input)
                    if isinstance(block.input, dict)
                    else str(block.input)
                )
                tool_input = (
                    tool_input[:150] + "..." if len(tool_input) > 150 else tool_input
                )
                prefix = (
                    f"mcp.{tool_name.replace('mcp__', '').replace('__', '.')}"
                    if tool_name.startswith("mcp__")
                    else tool_name
                )
                texts.append(f"\n🔧 {prefix} {tool_input}")
        return "\n".join(texts) if texts else None
    return msg if isinstance(msg, str) else None


async def preserve_memory():
    if ephemeral_mode or not CONVERSATION_HISTORY:
        return
    try:
        diff = await preserve_conversation_memory(CONVERSATION_HISTORY)
        if diff:
            print(f"\n{C['cyan']}📝 Memory updated:{C['reset']}")
            print(diff)
    except Exception as e:
        print(f"{C['yellow']}⚠️ Memory preservation failed: {e}{C['reset']}")


async def check_context_usage():
    if ephemeral_mode:
        return

    total_tokens = sum(len(str(msg)) // 4 for msg in CONVERSATION_HISTORY)
    if total_tokens >= MAX_CONTEXT_TOKENS:
        print(
            f"{C['yellow']}📊 Context limit reached, preserving memory...{C['reset']}"
        )
        await preserve_memory()
        CONVERSATION_HISTORY.clear()
        print(f"{C['green']}✅ Context cleared, continuing...{C['reset']}")


def signal_handler(signum, frame):
    global shutdown_count
    with shutdown_lock:
        shutdown_count += 1
        if shutdown_count == 1:
            print(
                f"\n{C['dim']}💤 vesta is tired and taking a nap to help remember stuff...{C['reset']}"
            )
            if SHUTDOWN_EVENT:
                SHUTDOWN_EVENT.set()
        elif shutdown_count > 2:
            print(f"\n{C['yellow']}⚡ Force shutdown!{C['reset']}")
            os._exit(0)


async def graceful_shutdown():
    try:
        await asyncio.wait_for(preserve_memory(), timeout=300.0)  # 5 minutes
    except asyncio.TimeoutError:
        print(f"{C['yellow']}⚠️ Memory preservation timeout{C['reset']}")
    except Exception as e:
        print(f"{C['yellow']}⚠️ Memory error: {e}{C['reset']}")

    CONVERSATION_HISTORY.clear()
    try:
        if CLIENT:
            await CLIENT.__aexit__(None, None, None)
    except Exception:
        pass
    print(f"{C['green']}✅ sweet dreams!{C['reset']}")


async def send_message(prompt, show_in_chat=True):
    client = await init_client()
    timestamp = datetime.now().strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")
    CONVERSATION_HISTORY.append({"role": "user", "content": prompt})

    try:
        await client.query(f"[Current time: {timestamp}]\n{prompt}")
        await check_context_usage()
    except Exception as e:
        error_msg = f"failed to send message: {str(e)[:100]}"
        print(f"{C['yellow']}⚠️ {error_msg}{C['reset']}")
        CONVERSATION_HISTORY.append({"role": "assistant", "content": error_msg})
        return [error_msg]

    responses, seen = [], set()
    try:

        async def collect():
            async for msg in client.receive_response():
                text = parse_message(msg)
                if text and text not in seen:
                    seen.add(text)
                    if show_in_chat:
                        for line in text.split("\n"):
                            if line.strip():
                                if line.startswith("🔧"):
                                    print(f"{C['yellow']}>{line}{C['reset']}")
                                else:
                                    responses.append(line)

        await asyncio.wait_for(collect(), timeout=300.0)
    except asyncio.TimeoutError:
        responses.append("[Response timeout after 5 minutes]")
    except Exception as e:
        responses.append(f"[Error: {str(e)[:100]}]")

    if responses:
        CONVERSATION_HISTORY.append(
            {"role": "assistant", "content": " ".join(responses)}
        )
    return responses


def print_header():
    print(f"\n{C['cyan']}╔{'═' * 58}╗")
    print(f"║{' ' * 23}{C['yellow']}🔥 VESTA{C['cyan']}{' ' * 27}║")
    print(f"╚{'═' * 58}╝{C['reset']}\n")


def start_whatsapp_bridge():
    script_path = Path(__file__).parent.parent.parent / "start_whatsapp_bridge.sh"
    if script_path.exists():
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


async def run_vesta():
    global SHUTDOWN_EVENT
    SHUTDOWN_EVENT = asyncio.Event()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Check if MEMORY.md exists, if not copy from template
    memory_file = Path(__file__).parent.parent.parent / "MEMORY.md"
    memory_template = Path(__file__).parent.parent.parent / "MEMORY.md.tmp"
    if not memory_file.exists() and memory_template.exists():
        import shutil

        shutil.copy(memory_template, memory_file)
        print(f"{C['dim']}📝 Created MEMORY.md from template{C['reset']}")

    print_header()
    start_whatsapp_bridge()

    last_proactive = datetime.now()
    last_bridge_check = datetime.now()
    message_queue = asyncio.Queue()

    def print_chat(text, sender=""):
        timestamp = datetime.now().strftime("%I:%M %p")
        colors = {"You": "cyan", "Vesta": "magenta", "System": "yellow"}
        if sender in colors:
            prefix = f"{C['dim']}[{timestamp}]{C['reset']} {C[colors[sender]]}{sender.lower()}:{C['reset']}"
            for line in text.split("\n"):
                if line.strip():
                    print(f"{prefix} {line}")
        else:
            print(
                f"{C['dim']}[{timestamp}]{C['reset']} {C['yellow']}{text}{C['reset']}"
            )

    async def show_typing():
        timestamp = datetime.now().strftime("%I:%M %p")
        dots = ["   ", ".  ", ".. ", "..."]
        dot_idx = 0
        while True:
            print(
                f"\r{C['dim']}[{timestamp}]{C['reset']} {C['magenta']}vesta{C['reset']} {C['dim']}is typing{dots[dot_idx]}{C['reset']}",
                end="",
                flush=True,
            )
            dot_idx = (dot_idx + 1) % 4
            await asyncio.sleep(0.5)
            # Will be cancelled when done typing

    async def process_queue():
        global IS_PROCESSING
        assert SHUTDOWN_EVENT is not None
        while not SHUTDOWN_EVENT.is_set():
            try:
                msg, is_user = await asyncio.wait_for(message_queue.get(), timeout=1.0)
                IS_PROCESSING = True

                # Add natural delay before typing
                await asyncio.sleep(
                    0.8 + datetime.now().microsecond / 3000000
                )  # 0.8-1.1s random delay

                # Show typing indicator
                typing_task = asyncio.create_task(show_typing())

                try:
                    responses = await send_message(msg, show_in_chat=is_user)
                except Exception as e:
                    responses = [f"something went wrong: {str(e)[:50]}"]
                    print(
                        f"{C['yellow']}⚠️ Message processing error: {str(e)[:100]}{C['reset']}"
                    )
                finally:
                    # Always cancel typing animation
                    typing_task.cancel()
                    try:
                        await typing_task
                    except asyncio.CancelledError:
                        pass

                    # Clear typing indicator line
                    print("\r\033[K", end="", flush=True)

                for i, response in enumerate(responses):
                    if response and response.strip():
                        if i > 0:
                            await asyncio.sleep(0.3)
                        print_chat(response, "Vesta")
                IS_PROCESSING = False
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"{C['yellow']}⚠️ Queue error: {str(e)[:100]}{C['reset']}")

    async def handle_input():
        assert SHUTDOWN_EVENT is not None
        while not SHUTDOWN_EVENT.is_set():
            try:
                user_msg = await aioconsole.ainput(f"{C['green']}>{C['reset']} ")
                if SHUTDOWN_EVENT.is_set():
                    break
                if not user_msg.strip():
                    continue
                print("\033[1A\033[K", end="")
                print_chat(user_msg, "You")
                await message_queue.put((user_msg.strip(), True))
            except (KeyboardInterrupt, EOFError):
                SHUTDOWN_EVENT.set()
                break
            except asyncio.CancelledError:
                break

    async def monitor():
        nonlocal last_proactive, last_bridge_check
        assert SHUTDOWN_EVENT is not None
        notification_buffer = []
        buffer_start_time = None
        icons = {"whatsapp": "📱", "scheduler": "⏰", "email": "📧"}

        while not SHUTDOWN_EVENT.is_set():
            try:
                await asyncio.sleep(NOTIFICATION_CHECK_INTERVAL)
            except asyncio.CancelledError:
                break
            if SHUTDOWN_EVENT.is_set():
                break

            now = datetime.now()
            if now - last_bridge_check >= timedelta(seconds=30):
                if not subprocess.run(
                    ["pgrep", "-f", "whatsapp-bridge"], capture_output=True, text=True
                ).stdout.strip():
                    print_chat(
                        "🔄 WhatsApp bridge disconnected, restarting...", "System"
                    )
                    start_whatsapp_bridge()
                last_bridge_check = now

            new_notifs = await process_notifications()
            if new_notifs:
                for notif in new_notifs:
                    meta = notif.get("metadata", {})
                    sender = meta.get("chat_name", meta.get("sender", notif["source"]))
                    icon = icons.get(notif["source"], "🔔")
                    msg = notif["message"]
                    print_chat(
                        f"{icon} {sender}: {msg[:200] + '...' if len(msg) > 200 else msg}",
                        "System",
                    )

                notification_buffer.extend(new_notifs)
                if buffer_start_time is None:
                    buffer_start_time = now

            if (
                notification_buffer
                and buffer_start_time
                and (now - buffer_start_time).total_seconds()
                >= (0 if IS_PROCESSING else 3)
            ):
                if len(notification_buffer) == 1:
                    notif = notification_buffer[0]
                    meta_str = (
                        f" (metadata: {', '.join(f'{k}={v}' for k, v in notif.get('metadata', {}).items() if v)})"
                        if notif.get("metadata")
                        else ""
                    )
                    prompt = f"[{notif['type']} from {notif['source']} at {notif['timestamp']}]{meta_str}: {notif['message']}"
                    await message_queue.put((prompt, True))
                else:
                    print_chat(
                        f"📦 Processing {len(notification_buffer)} notifications together...",
                        "System",
                    )
                    prompt_parts = [
                        f"[{len(notification_buffer)} notifications received]"
                    ]
                    for notif in notification_buffer:
                        meta = notif.get("metadata", {})
                        sender = meta.get(
                            "chat_name", meta.get("sender", notif["source"])
                        )
                        prompt_parts.append(f"{sender}: {notif['message']}")
                    await message_queue.put(("\n".join(prompt_parts), True))

                notification_buffer = []
                buffer_start_time = None

            if now - last_proactive >= timedelta(minutes=PROACTIVE_CHECK_INTERVAL):
                print_chat("⏰ Running 30-minute check...", "System")
                await message_queue.put(
                    (
                        "It's been 30 minutes. Is there anything useful you could do right now?",
                        False,
                    )
                )
                last_proactive = now

    tasks = [
        asyncio.create_task(t) for t in [handle_input(), process_queue(), monitor()]
    ]

    try:
        await SHUTDOWN_EVENT.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        SHUTDOWN_EVENT.set()

    for task in tasks:
        task.cancel()
    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=2.0
        )
    except asyncio.TimeoutError:
        pass

    try:
        await asyncio.wait_for(
            graceful_shutdown(), timeout=310.0
        )  # 5+ minutes for memory preservation
    except asyncio.TimeoutError:
        print(f"{C['yellow']}⚠️ Shutdown timeout{C['reset']}")


def main():
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
