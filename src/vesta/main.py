import asyncio
import json
import os
import logging
import signal
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

import aioconsole
from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions
from claude_code_sdk.types import (
    McpStdioServerConfig,
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
    ResultMessage,
)

from .memory_agent import preserve_conversation_memory

# Configuration
ephemeral_mode = os.environ.get('EPHEMERAL', '').lower() == 'true'

# Suppress logging
logging.basicConfig(level=logging.ERROR)
for logger in ['mcp', 'fastmcp', 'asyncio']:
    logging.getLogger(logger).setLevel(logging.ERROR)

if ephemeral_mode:
    print("💨 EPHEMERAL MODE - Memory preservation disabled")

MCP_SERVERS = {
    "microsoft": {
        "command": "uv",
        "args": ["run", "--directory", "mcps/microsoft-mcp", "microsoft-mcp"]
    },
    "whatsapp": {
        "command": "uv",
        "args": ["run", "--directory", "mcps/whatsapp-mcp/whatsapp-mcp-server", "main.py"]
    },
    "scheduler": {
        "command": "uv",
        "args": ["run", "--directory", "mcps/scheduler-mcp", "scheduler-mcp"]
    }
}

NOTIFICATION_CHECK_INTERVAL = 2  # seconds
PROACTIVE_CHECK_INTERVAL = 30  # minutes
MAX_CONTEXT_TOKENS = 180000  # Claude's context is ~200k, preserve at 180k
CONTEXT_SIZE_THRESHOLD = 0.9  # Preserve memory when 90% of context used

class Colors:
    RESET = '\033[0m'
    DIM = '\033[2m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_GREEN = '\033[92m'
    YELLOW = '\033[33m'

CLIENT = None
CONVERSATION_HISTORY = []
SHUTDOWN_EVENT: asyncio.Event | None = None
SHUTDOWN_COUNT = 0

def load_prompts():
    prompts = []
    paths = [
        Path(__file__).parent.parent.parent / "SYSTEM_PROMPT.md",
        Path.home() / ".prompts" / "python-coding.md"
    ]

    for path in paths:
        if path.exists():
            prompts.append(path.read_text())

    return "\n\n".join(prompts) if prompts else "You are Vesta, a helpful AI assistant."

def get_mcp_config():
    config = {}
    root_dir = Path(__file__).parent.parent.parent.absolute()

    for name, server in MCP_SERVERS.items():
        config[name] = McpStdioServerConfig(
            command=server["command"],
            args=server["args"],
            env={
                "PYTHONUNBUFFERED": "1",
                "NOTIFICATIONS_DIR": str(root_dir / "notifications"),
                "DATA_DIR": str(root_dir / "data")
            }
        )
    return config

async def process_notifications():
    notif_dir = Path(__file__).parent.parent.parent / "notifications"
    if not notif_dir.exists():
        return []

    notifications = []
    for file in notif_dir.glob("*.json"):
        try:
            data = json.loads(file.read_text())
            notifications.append(data)
            file.unlink()
        except Exception as e:
            logging.error(f"Failed to process notification {file}: {e}")

    return notifications

async def init_client():
    global CLIENT
    if CLIENT:
        return CLIENT

    options = ClaudeCodeOptions(
        system_prompt=load_prompts(),
        mcp_servers=get_mcp_config(),
        hooks={},
        permission_mode="bypassPermissions"
    )

    CLIENT = ClaudeSDKClient(options=options)
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
                tool_input = json.dumps(block.input) if isinstance(block.input, dict) else str(block.input)

                if len(tool_input) > 60:
                    tool_input = tool_input[:57] + "..."

                if tool_name.startswith('mcp__'):
                    tool_display = tool_name.replace('mcp__', '').replace('__', '.')
                    texts.append(f"🔧 mcp.{tool_display} {tool_input}")
                else:
                    texts.append(f"🔧 {tool_name} {tool_input}")

        return '\n'.join(texts) if texts else None

    elif isinstance(msg, ResultMessage):
        return None
    elif isinstance(msg, str):
        return msg

    return None

async def preserve_memory():
    global CONVERSATION_HISTORY

    if ephemeral_mode:
        return

    if not CONVERSATION_HISTORY:
        return

    print(f"{Colors.YELLOW}📝 Preserving memory...{Colors.RESET}")

    try:
        await preserve_conversation_memory(CONVERSATION_HISTORY)
        CONVERSATION_HISTORY.clear()
    except Exception as e:
        print(f"{Colors.YELLOW}⚠️ Memory preservation failed: {e}{Colors.RESET}")

def estimate_tokens(text):
    # Rough estimate: ~4 characters per token
    return len(text) // 4

async def check_context_usage():
    global CONVERSATION_HISTORY

    if ephemeral_mode:
        return

    total_tokens = sum(estimate_tokens(str(msg)) for msg in CONVERSATION_HISTORY)

    if total_tokens >= MAX_CONTEXT_TOKENS:
        await preserve_memory()

def signal_handler(signum, frame):
    global SHUTDOWN_COUNT
    SHUTDOWN_COUNT += 1

    if SHUTDOWN_COUNT == 1:
        print(f"\n{Colors.YELLOW}📝 Preserving memory...{Colors.RESET}")
        if SHUTDOWN_EVENT:
            SHUTDOWN_EVENT.set()
    else:
        print(f"\n{Colors.YELLOW}⚡ Force shutdown!{Colors.RESET}")
        import sys
        sys.exit(0)

async def graceful_shutdown():
    await preserve_memory()

    if CLIENT:
        await CLIENT.__aexit__(None, None, None)

    print(f"{Colors.BRIGHT_GREEN}✅ Vesta shutdown complete{Colors.RESET}")

async def send_message(prompt, show_in_chat=True):
    global CONVERSATION_HISTORY

    client = await init_client()

    timestamp = datetime.now().strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")
    full_prompt = f"[Current time: {timestamp}]\n{prompt}"

    # Track conversation
    CONVERSATION_HISTORY.append({"role": "user", "content": prompt})

    await client.query(full_prompt)

    # Check if we need to preserve memory
    await check_context_usage()

    responses = []
    seen = set()

    try:
        async def collect_responses():
            async for msg in client.receive_response():
                text = parse_message(msg)
                if text and text not in seen:
                    seen.add(text)
                    if show_in_chat:
                        for line in text.split('\n'):
                            if line.strip():
                                if line.startswith('🔧'):
                                    print(f"{Colors.BRIGHT_YELLOW}> {line}{Colors.RESET}")
                                else:
                                    responses.append(line)

        await asyncio.wait_for(collect_responses(), timeout=30.0)
    except asyncio.TimeoutError:
        responses.append("[Response timeout]")
    except Exception as e:
        responses.append(f"[Error: {e}]")

    # Track assistant response
    if responses:
        CONVERSATION_HISTORY.append({"role": "assistant", "content": " ".join(responses)})

    return responses

def print_header():
    print(f"\n{Colors.BRIGHT_CYAN}╔" + "═"*58 + "╗")
    print("║" + " "*20 + f"{Colors.BRIGHT_YELLOW}🌟 VESTA v2.0{Colors.BRIGHT_CYAN}" + " "*25 + "║")
    print("╠" + "═"*58 + "╣")
    print("║  💬 Type and press Enter  |  🛑 Exit: Ctrl+C" + " "*10 + "║")
    print("╚" + "═"*58 + f"╝{Colors.RESET}\n")

def start_whatsapp_bridge():
    """Start the WhatsApp bridge if the startup script exists"""
    script_path = Path(__file__).parent.parent.parent / "start_whatsapp_bridge.sh"
    if script_path.exists():
        try:
            # Always use --force to kill existing bridges first
            result = subprocess.run([str(script_path), "--force"], capture_output=True, text=True)
            if result.returncode == 0:
                print(f"{Colors.BRIGHT_GREEN}✓ WhatsApp bridge started{Colors.RESET}")
            else:
                print(f"{Colors.YELLOW}⚠ WhatsApp bridge startup issue: {result.stderr}{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.YELLOW}⚠ Could not start WhatsApp bridge: {e}{Colors.RESET}")

async def run_vesta():
    global SHUTDOWN_EVENT
    SHUTDOWN_EVENT = asyncio.Event()

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print_header()
    start_whatsapp_bridge()

    last_proactive = datetime.now()
    proactive_interval = timedelta(minutes=PROACTIVE_CHECK_INTERVAL)
    message_queue = asyncio.Queue()

    def print_timestamp():
        return datetime.now().strftime("%I:%M %p")

    def print_chat(text, sender=""):
        timestamp = print_timestamp()

        if sender == "You":
            print(f"{Colors.DIM}[{timestamp}]{Colors.RESET} {Colors.BRIGHT_CYAN}you:{Colors.RESET} {text}")
        elif sender == "Vesta":
            for line in text.split('\n'):
                if line.strip():
                    print(f"{Colors.DIM}[{timestamp}]{Colors.RESET} {Colors.BRIGHT_MAGENTA}vesta:{Colors.RESET} {line}")
        elif sender == "System":
            print(f"{Colors.DIM}[{timestamp}]{Colors.RESET} {Colors.YELLOW}{text}{Colors.RESET}")

    async def process_message_queue():
        assert SHUTDOWN_EVENT is not None
        while not SHUTDOWN_EVENT.is_set():
            try:
                msg, is_user = await asyncio.wait_for(message_queue.get(), timeout=1.0)
                responses = await send_message(msg, show_in_chat=is_user)
                for i, response in enumerate(responses):
                    if response and response.strip():
                        if i > 0:
                            await asyncio.sleep(0.3)
                        print_chat(response, "Vesta")
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print_chat(f"Error: {e}", "System")

    async def handle_user_input():
        assert SHUTDOWN_EVENT is not None
        while not SHUTDOWN_EVENT.is_set():
            try:
                user_msg = await aioconsole.ainput(f"{Colors.BRIGHT_GREEN}>{Colors.RESET} ")
                if SHUTDOWN_EVENT.is_set():
                    break
                if not user_msg.strip():
                    continue

                print(f"\033[1A\033[K", end="")
                print_chat(user_msg, "You")
                await message_queue.put((user_msg.strip(), True))
            except (KeyboardInterrupt, EOFError):
                SHUTDOWN_EVENT.set()
                break
            except asyncio.CancelledError:
                break

    async def monitor_system():
        nonlocal last_proactive
        assert SHUTDOWN_EVENT is not None

        while not SHUTDOWN_EVENT.is_set():
            try:
                await asyncio.sleep(NOTIFICATION_CHECK_INTERVAL)
            except asyncio.CancelledError:
                break

            if SHUTDOWN_EVENT.is_set():
                break

            notifications = await process_notifications()
            for notif in notifications:
                source = notif['source']
                data = notif['data']
                timestamp = notif['timestamp']

                if source == 'whatsapp':
                    sender = data.get('sender', 'Unknown')
                    chat_name = data.get('chat_name', sender)
                    content = data.get('content', data.get('message', ''))
                    media_type = data.get('media_type', '')

                    if media_type:
                        display = f"📱 WhatsApp [{chat_name}]: [{media_type}] {content[:50]}..."
                    else:
                        display = f"📱 WhatsApp [{chat_name}]: {content[:80]}..."

                    prompt = f"[WhatsApp message at {timestamp}] From {chat_name} ({sender}): {content}"
                else:
                    content = data.get('message', str(data))
                    display = f"🔔 {source}: {content[:80]}..."
                    prompt = f"[Notification at {timestamp}] From {source}: {content}"

                print_chat(display, "System")
                await message_queue.put((prompt, True))

            now = datetime.now()
            if now - last_proactive >= proactive_interval:
                print_chat("⏰ Running 30-minute check...", "System")
                await message_queue.put(("It's been 30 minutes. Is there anything useful you could do right now?", False))
                last_proactive = now

    tasks = [
        asyncio.create_task(handle_user_input()),
        asyncio.create_task(process_message_queue()),
        asyncio.create_task(monitor_system())
    ]

    try:
        await SHUTDOWN_EVENT.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        SHUTDOWN_EVENT.set()

    # Cancel all tasks
    for task in tasks:
        task.cancel()

    # Wait for tasks to finish
    await asyncio.gather(*tasks, return_exceptions=True)

    # Run graceful shutdown
    await graceful_shutdown()

def main():
    try:
        asyncio.run(run_vesta())
    except KeyboardInterrupt:
        print("\n👋 Bye!")
    except Exception as e:
        print(f"\n💥 Fatal error: {e}")
        raise

if __name__ == "__main__":
    main()