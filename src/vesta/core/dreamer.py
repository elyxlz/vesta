"""Dreamer Agent - consolidates memories and skills for Vesta."""

import asyncio
import collections.abc as cab
import contextlib
import datetime as dt
import difflib
import json
import pathlib as pl
import shutil
import time

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

import vesta.models as vm
from vesta import logger
from vesta.config import Messages
from vesta.models import ConversationMessage
from vesta.core.init import (
    get_memory_dir,
    get_memory_path,
    get_memory_backup_dir,
    get_skills_dir,
    get_dreamer_prompt_path,
    load_memory_template,
)

ProgressCallback = cab.Callable[[str], object] | None


def load_memory(config: vm.VestaConfig) -> str:
    """Load main agent memory from disk or template."""
    memory_path = get_memory_path(config)
    if memory_path.exists():
        content = memory_path.read_text()
        logger.debug(f"[DREAMER] Loaded main memory ({len(content)} chars)")
        return content
    logger.debug("[DREAMER] Using template for main (file not found)")
    return load_memory_template("main")


def _get_dir_size(path: pl.Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def backup_all_memories(config: vm.VestaConfig) -> pl.Path | None:
    memory_dir = get_memory_dir(config)
    if not memory_dir.exists():
        logger.debug("[DREAMER] No memory folder to backup")
        return None

    backup_base = get_memory_backup_dir(config)
    backup_base.mkdir(parents=True, exist_ok=True)

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_base / timestamp
    shutil.copytree(memory_dir, backup_path)

    size_kb = _get_dir_size(backup_path) / 1024
    logger.info(f"[DREAMER] Backup created: {backup_path.name} ({size_kb:.1f} KB)")
    return backup_path


def _format_diff(before: str, after: str) -> str:
    colors = {"+": "\033[92m", "-": "\033[91m", "@": "\033[96m"}
    diff = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), n=1)
    return "\n".join(f"{colors.get(line[0], '')}{line.rstrip()}\033[0m" if line[0] in colors else line.rstrip() for line in list(diff)[2:])


def _validate_memory_path(path: pl.Path, *, config: vm.VestaConfig) -> None:
    memory_dir = get_memory_dir(config)
    try:
        path.resolve().relative_to(memory_dir.resolve())
    except ValueError:
        raise ValueError(f"Memory path {path} outside memory directory {memory_dir}")


async def _call_progress(callback: ProgressCallback, message: str) -> None:
    if callback:
        result = callback(message)
        if asyncio.iscoroutine(result):
            await result


def format_conversation(history: list[ConversationMessage]) -> str:
    return "\n".join(f"{msg['role']}: {msg['content']}" for msg in history)


def get_cli_session_history(working_dir: str) -> list[ConversationMessage]:
    projects_dir = pl.Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return []

    project_name = f"-{working_dir.replace('/', '-')}"
    project_dir = projects_dir / project_name

    if not project_dir.exists():
        return []

    session_files = sorted(project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not session_files:
        return []

    session_file = session_files[0]
    messages = []

    with open(session_file) as f:
        for line in f:
            data = json.loads(line)

            if data.get("type") == "user_message":
                content = data.get("content", "")
                if isinstance(content, list):
                    text_parts = [block.get("text", "") for block in content if block.get("type") == "text"]
                    content = " ".join(text_parts)
                messages.append({"role": "user", "content": str(content)})

            elif data.get("type") == "assistant_message":
                content = data.get("content", "")
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_name = block.get("name", "unknown_tool")
                            text_parts.append(f"[used tool: {tool_name}]")
                    content = " ".join(text_parts)
                messages.append({"role": "assistant", "content": str(content)})

    return messages


async def preserve_conversation_memory(
    conversation_history: list[ConversationMessage] | None = None,
    *,
    config: vm.VestaConfig,
    progress_callback: ProgressCallback = None,
) -> str:
    start_time = time.monotonic()

    if conversation_history is None:
        await _call_progress(progress_callback, "Loading conversation history from CLI session...")
        conversation_history = get_cli_session_history(str(config.root_dir))

    if not conversation_history:
        await _call_progress(progress_callback, "No conversation history available")
        logger.debug("[DREAMER] No conversation history to preserve")
        return ""

    logger.info(f"[DREAMER] Preserving main memory from {len(conversation_history)} messages")
    await _call_progress(progress_callback, "Loading MEMORY.md...")

    memory_path = get_memory_path(config)
    _validate_memory_path(memory_path, config=config)
    before = memory_path.read_text() if memory_path.exists() else ""
    before_size = len(before)
    logger.debug(f"[DREAMER] Current main memory: {before_size} chars")

    await _call_progress(progress_callback, f"Building update prompt from {len(conversation_history)} messages...")

    prompt = f"""Current MEMORY.md:
{before}

Recent conversation to process:
{format_conversation(conversation_history)}

Check MEMORY.md and update it with any new important information from this conversation."""

    await _call_progress(progress_callback, "Dreamer Agent awakening...")
    logger.debug("[DREAMER] Spawning Dreamer Agent")

    skills_dir = get_skills_dir(config)
    dreamer_prompt_path = get_dreamer_prompt_path(config)
    dreamer_prompt_template = dreamer_prompt_path.read_text()
    memory_prompt = dreamer_prompt_template.format(
        memory_path=memory_path,
        skills_dir=skills_dir,
        dreamer_prompt_path=dreamer_prompt_path,
    )

    async with ClaudeSDKClient(
        options=ClaudeAgentOptions(
            system_prompt=memory_prompt,
            permission_mode="bypassPermissions",
            model="sonnet",
            cwd=config.state_dir,
            add_dirs=[str(config.state_dir), str(skills_dir)],
            max_thinking_tokens=config.max_thinking_tokens,
        )
    ) as client:
        await _call_progress(progress_callback, f"Dreamer processing {len(conversation_history)} messages...")
        await client.query(prompt)
        await _call_progress(progress_callback, "Dreamer is dreaming...")
        async for msg in client.receive_response():
            # Log dreamer's actions
            if hasattr(msg, "content") and msg.content:
                for block in msg.content:
                    if hasattr(block, "type"):
                        if block.type == "text" and hasattr(block, "text") and block.text:
                            for line in block.text.strip().split("\n"):
                                if line.strip():
                                    logger.info(f"[DREAMER] {line.strip()}")
                        elif block.type == "tool_use" and hasattr(block, "name"):
                            logger.info(f"[DREAMER] Using tool: {block.name}")

    elapsed = time.monotonic() - start_time
    await _call_progress(progress_callback, "Computing diff vs MEMORY.md...")

    after = memory_path.read_text() if memory_path.exists() else ""
    after_size = len(after)

    if before == after:
        await _call_progress(progress_callback, "No changes detected")
        logger.info(f"[DREAMER] Main memory unchanged after {elapsed:.1f}s")
        return ""

    logger.info(f"[DREAMER] Main memory updated: {before_size} -> {after_size} chars ({elapsed:.1f}s)")

    return _format_diff(before, after)


# Memory preservation orchestration


async def _get_and_clear_subagent_conversations(state: vm.State) -> dict[str, list[str]]:
    async with state.subagent_conversations_lock:
        conversations = state.subagent_conversations.copy()
        state.subagent_conversations.clear()
        return conversations


async def _get_and_clear_conversation_history(state: vm.State) -> list[ConversationMessage]:
    async with state.conversation_history_lock:
        history = state.conversation_history.copy()
        state.conversation_history.clear()
        return history


@contextlib.asynccontextmanager
async def _heartbeat_logger(message_fn: cab.Callable[[], str], *, interval: float) -> cab.AsyncIterator[None]:
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


async def preserve_memory(state: vm.State, *, config: vm.VestaConfig) -> bool:
    """Run Dreamer Agent to consolidate memories. Returns True if memory was updated."""
    if config.ephemeral:
        logger.info("[DREAMER] Skipping (ephemeral mode)")
        return False

    logger.info("[DREAMER] Starting consolidation...")

    def log_progress(message: str) -> None:
        logger.info(f"[DREAMER] {message}")

    start_time = dt.datetime.now()

    def heartbeat_message() -> str:
        elapsed = int((dt.datetime.now() - start_time).total_seconds())
        return f"[DREAMER] Still dreaming... {elapsed}s elapsed"

    async with _heartbeat_logger(heartbeat_message, interval=30):
        history = await _get_and_clear_conversation_history(state)
        subagent_convos = await _get_and_clear_subagent_conversations(state)

        # Append subagent conversations to conversation history for memory agent
        if subagent_convos:
            for agent_name, convos in subagent_convos.items():
                if convos:
                    combined_text = "\n---\n".join(convos)
                    history.append(
                        {
                            "role": "assistant",
                            "content": f"[Subagent {agent_name} interactions]\n{combined_text}",
                        }
                    )

        if not history:
            logger.info("[DREAMER] No conversation history to preserve")
            return False

        backup_path = backup_all_memories(config)

        diff = await preserve_conversation_memory(
            history,
            config=config,
            progress_callback=log_progress,
        )

        elapsed = (dt.datetime.now() - start_time).total_seconds()

        if diff:
            logger.info(Messages.DREAMER_UPDATED)
            logger.info("--- main memory ---")
            logger.info(diff)
            if backup_path:
                diff_file = backup_path / "DIFF.txt"
                with diff_file.open("w") as f:
                    f.write("=== main ===\n")
                    f.write(diff)
                    f.write("\n\n")
            logger.info(f"[DREAMER] Total preservation time: {elapsed:.1f}s")
            return True
        else:
            logger.info(f"[DREAMER] No significant updates ({elapsed:.1f}s)")
            return False
