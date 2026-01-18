"""Dreamer Agent - consolidates memories and skills for Vesta."""

import asyncio
import collections.abc as cab
import contextlib
import datetime as dt
import difflib
import json
import pathlib as pl
import time
import zipfile

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, TextBlock, ThinkingBlock, ToolUseBlock, ToolResultBlock

import vesta.models as vm
from vesta import logger
from vesta.models import ConversationMessage
from vesta.core.init import (
    get_memory_dir,
    get_memory_path,
    get_backups_dir,
    get_skills_dir,
    load_memory_template,
)
from vesta.templates.dreamer import PROMPT_TEMPLATE as DREAMER_PROMPT_TEMPLATE

ProgressCallback = cab.Callable[[str], object] | None


def load_memory(config: vm.VestaConfig) -> str:
    """Load main agent memory from disk or template."""
    memory_path = get_memory_path(config)
    if memory_path.exists():
        content = memory_path.read_text()
        logger.debug(f"Loaded main memory ({len(content)} chars)")
        return content
    logger.debug("Using template for main (file not found)")
    return load_memory_template("main")


def backup_state(config: vm.VestaConfig) -> pl.Path | None:
    """Backup entire state_dir as timestamped zip, excluding logs/notifications/backups."""
    backup_dir = get_backups_dir(config)
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = backup_dir / f"vesta-{timestamp}.zip"
    exclude = {"logs", "notifications", "backups", "onedrive"}

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in config.state_dir.iterdir():
            if item.name in exclude:
                continue
            try:
                if item.is_file():
                    zf.write(item, item.name)
                elif item.is_dir():
                    for file in item.rglob("*"):
                        try:
                            if file.is_file():
                                zf.write(file, file.relative_to(config.state_dir))
                        except (PermissionError, OSError):
                            continue
            except (PermissionError, OSError):
                continue

    size_kb = zip_path.stat().st_size / 1024
    logger.dreamer(f"Backup created: {zip_path.name} ({size_kb:.1f} KB)")
    return zip_path


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


def _snapshot_memory_dir(config: vm.VestaConfig) -> dict[str, str]:
    """Capture current state of all memory files."""
    memory_dir = get_memory_dir(config)
    snapshot: dict[str, str] = {}

    if not memory_dir.exists():
        return snapshot

    for file in memory_dir.rglob("*.md"):
        rel_path = str(file.relative_to(memory_dir))
        try:
            snapshot[rel_path] = file.read_text()
        except OSError:
            pass

    return snapshot


def _compute_all_diffs(before: dict[str, str], after: dict[str, str]) -> dict[str, str]:
    """Compute diffs for all changed files."""
    diffs: dict[str, str] = {}
    all_paths = set(before.keys()) | set(after.keys())

    for path in sorted(all_paths):
        before_content = before.get(path, "")
        after_content = after.get(path, "")

        if before_content != after_content:
            diffs[path] = _format_diff(before_content, after_content)

    return diffs


async def _call_progress(callback: ProgressCallback, message: str) -> None:
    if callback:
        result = callback(message)
        if asyncio.iscoroutine(result):
            await result


def _format_conversation(history: list[ConversationMessage]) -> str:
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
        logger.debug("No conversation history to preserve")
        return ""

    logger.dreamer(f"Preserving memory from {len(conversation_history)} messages")
    await _call_progress(progress_callback, "Snapshotting memory files...")

    # Capture state of ALL memory files before dreamer runs
    before_snapshot = _snapshot_memory_dir(config)
    logger.debug(f"Captured {len(before_snapshot)} memory files")

    memory_path = get_memory_path(config)
    current_memory = before_snapshot.get("MEMORY.md", "")

    await _call_progress(progress_callback, f"Building update prompt from {len(conversation_history)} messages...")

    prompt = f"""Current MEMORY.md:
{current_memory}

Recent conversation to process:
{_format_conversation(conversation_history)}

Check MEMORY.md and update it with any new important information from this conversation."""

    await _call_progress(progress_callback, "Dreamer Agent awakening...")
    logger.debug("Spawning Dreamer Agent")

    logger.debug("Getting paths...")
    skills_dir = get_skills_dir(config)

    logger.debug("Formatting prompt...")
    memory_prompt = DREAMER_PROMPT_TEMPLATE.format(
        memory_path=memory_path,
        skills_dir=skills_dir,
    )

    logger.debug("Creating SDK client...")
    async with ClaudeSDKClient(
        options=ClaudeAgentOptions(
            system_prompt=memory_prompt,
            permission_mode="bypassPermissions",
            model="sonnet",
            cwd=config.memory_dir,
            add_dirs=[str(config.memory_dir), str(skills_dir)],
            max_thinking_tokens=config.max_thinking_tokens,
        )
    ) as client:
        logger.debug("SDK client created")
        await _call_progress(progress_callback, f"Dreamer processing {len(conversation_history)} messages...")
        logger.dreamer("SDK client created, sending query...")
        await client.query(prompt)
        logger.dreamer("Query sent, waiting for response...")

        async def collect_response() -> None:
            async for msg in client.receive_response():
                content = getattr(msg, "content", None)
                if not content:
                    continue
                for block in content:
                    if isinstance(block, ThinkingBlock):
                        thinking = getattr(block, "thinking", "")
                        preview = thinking[:300] + "..." if len(thinking) > 300 else thinking
                        logger.dreamer(f"💭 {preview}")
                    elif isinstance(block, TextBlock):
                        text = getattr(block, "text", "")
                        for line in text.strip().split("\n"):
                            if line.strip():
                                logger.dreamer(line.strip())
                    elif isinstance(block, ToolUseBlock):
                        tool_name = getattr(block, "name", "unknown")
                        tool_input = getattr(block, "input", {})
                        input_preview = str(tool_input)[:100]
                        logger.dreamer(f"🔧 {tool_name}: {input_preview}")
                    elif isinstance(block, ToolResultBlock):
                        result = getattr(block, "content", "")
                        result_preview = str(result)[:200]
                        logger.dreamer(f"✓ Result: {result_preview}")

        try:
            await asyncio.wait_for(collect_response(), timeout=300)  # 5 min timeout
            logger.dreamer("Response complete")
        except TimeoutError:
            logger.error("Dreamer timeout - SDK hung for 5 minutes")
            return ""

    elapsed = time.monotonic() - start_time
    await _call_progress(progress_callback, "Computing diffs for all memory files...")

    # Capture after state and compute all diffs
    after_snapshot = _snapshot_memory_dir(config)
    all_diffs = _compute_all_diffs(before_snapshot, after_snapshot)

    if not all_diffs:
        await _call_progress(progress_callback, "No changes detected")
        logger.dreamer(f"Memory unchanged after {elapsed:.1f}s")
        return ""

    logger.dreamer(f"Updated {len(all_diffs)} file(s) in {elapsed:.1f}s")

    return "\n".join(f"--- {path} ---\n{diff}" for path, diff in all_diffs.items())


# Memory preservation orchestration


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
        logger.dreamer("Skipping (ephemeral mode)")
        return False

    logger.dreamer("Starting consolidation...")

    def log_progress(message: str) -> None:
        logger.dreamer(message)

    start_time = dt.datetime.now()

    def heartbeat_message() -> str:
        elapsed = int((dt.datetime.now() - start_time).total_seconds())
        return f"Still dreaming... {elapsed}s elapsed"

    async with _heartbeat_logger(heartbeat_message, interval=10):
        # Copy history WITHOUT clearing (will clear after success)
        logger.dreamer("Copying conversation history...")
        async with state.conversation_history_lock:
            history = state.conversation_history.copy()
        logger.dreamer(f"Got {len(history)} messages from conversation history")

        async with state.subagent_conversations_lock:
            subagent_convos = state.subagent_conversations.copy()
        logger.dreamer(f"Got {len(subagent_convos)} subagent conversations")

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

        # Fallback to CLI session if no history
        if not history:
            logger.dreamer("No conversation history, trying CLI session fallback...")
            history = get_cli_session_history(str(config.root_dir))

        if not history:
            logger.dreamer("No conversation history to preserve")
            return False

        logger.dreamer("Creating backup...")
        backup_state(config)

        logger.dreamer("Starting memory preservation...")
        diff = await preserve_conversation_memory(
            history,
            config=config,
            progress_callback=log_progress,
        )

        elapsed = (dt.datetime.now() - start_time).total_seconds()

        # Only clear history AFTER successful preservation
        async with state.conversation_history_lock:
            state.conversation_history.clear()
        async with state.subagent_conversations_lock:
            state.subagent_conversations.clear()
        logger.dreamer("Cleared conversation history after preservation")

        if diff:
            logger.dreamer("Memories consolidated:")
            logger.info("--- memory changes ---")
            logger.info(diff)
            logger.dreamer(f"Total preservation time: {elapsed:.1f}s")
            return True
        else:
            logger.dreamer(f"No significant updates ({elapsed:.1f}s)")
            return False
