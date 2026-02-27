"""Background processing loops."""

import asyncio
import pathlib as pl
import shutil

from claude_agent_sdk import ClaudeSDKClient, ClaudeSDKError

import vesta.models as vm
import vesta.core.effects as vfx
from vesta import logger
from vesta.core.client import process_message, build_client_options
from vesta.core.init import get_memory_path, load_prompt
from vesta.core import notifications as notifs


def build_dreamer_prompt(config: vm.VestaConfig) -> str:
    content = load_prompt("dreamer", config) or ""
    return content.format(
        memory_path=get_memory_path(config),
        skills_dir=config.skills_dir,
        prompts_dir=config.prompts_dir,
        conversations_dir=config.conversations_dir,
        dreamer_dir=config.dreamer_dir,
        install_root=config.install_root,
        repo_root=config.repo_root,
    )


async def _process_message_safely(msg: str, *, is_user: bool, state: vm.State, config: vm.VestaConfig) -> None:
    try:
        if not is_user:
            preview = msg[:200] + "..." if len(msg) > 200 else msg
            logger.system(preview.replace("\n", " "))
        responses, _ = await process_message(msg, state=state, config=config, is_user=is_user)
        for response in responses:
            if response and response.strip():
                logger.assistant(response)
    except (ClaudeSDKError, OSError, RuntimeError, ValueError, TimeoutError) as e:
        logger.error(f"Error processing message: {e}")
        state.pending_context = f"[System: Previous request failed with error: {e}. Session was reset.]"


async def message_processor(queue: asyncio.Queue, *, state: vm.State, config: vm.VestaConfig) -> None:
    while state.shutdown_event and not state.shutdown_event.is_set():
        logger.client("Creating new client session...")
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client:
            state.client = client
            logger.client("Client session started")

            if state.pending_context:
                await queue.put((state.pending_context, False))
                state.pending_context = None

            while not state.shutdown_event.is_set() and state.pending_context is None:
                try:
                    msg, is_user = await asyncio.wait_for(queue.get(), timeout=1.0)
                except TimeoutError:
                    continue

                await _process_message_safely(msg, is_user=is_user, state=state, config=config)

                if state.dreamer_active:
                    state.dreamer_active = False
                    _trigger_nightly_restart(state=state, config=config)

        state.client = None
        logger.client("Client session closed")


async def check_proactive_task(queue: asyncio.Queue, *, config: vm.VestaConfig) -> None:
    prompt = load_prompt("proactive_check", config)
    if not prompt:
        return
    prompt = prompt.replace("{proactive_check_interval}", str(config.proactive_check_interval))
    logger.proactive(f"Running {config.proactive_check_interval}-minute check...")
    await queue.put((prompt, False))


def _session_jsonl_path(state: vm.State, config: vm.VestaConfig) -> pl.Path | None:
    if not state.session_id:
        return None
    slug = str(config.state_dir).replace("/", "-")
    path = pl.Path.home() / ".claude" / "projects" / slug / f"{state.session_id}.jsonl"
    if path.exists():
        return path
    return None


def archive_conversation(state: vm.State, config: vm.VestaConfig) -> None:
    src = _session_jsonl_path(state, config)
    if not src:
        logger.dreamer("No session transcript to archive")
        return

    config.conversations_dir.mkdir(parents=True, exist_ok=True)
    now = vfx.get_current_time()
    dest = config.conversations_dir / f"{now.strftime('%Y-%m-%d_%H%M%S')}.jsonl"
    shutil.copy2(src, dest)
    logger.dreamer(f"Archived conversation to {dest}")


def _trigger_nightly_restart(*, state: vm.State, config: vm.VestaConfig) -> None:
    logger.dreamer("Dreamer complete, triggering nightly restart...")
    state.session_id = None
    config.session_file.unlink(missing_ok=True)

    summary = ""
    today = vfx.get_current_time().strftime("%Y-%m-%d")
    summary_path = config.dreamer_dir / f"{today}.md"
    if summary_path.exists():
        summary = f"\n\nDreamer summary:\n{summary_path.read_text().strip()}"

    greeting = load_prompt("returning_start", config) or ""
    if greeting.strip():
        greeting = f"\n\n{greeting.strip()}"

    state.pending_context = f"[System: Good morning. Vesta restarted with fresh memory after nightly dreamer run.]{summary}{greeting}"


async def process_nightly_memory(queue: asyncio.Queue, *, state: vm.State, config: vm.VestaConfig) -> None:
    if config.ephemeral:
        return

    now = vfx.get_current_time()
    if config.nightly_memory_hour is not None and now.hour == config.nightly_memory_hour:
        if state.last_dreamer_run is None or now.date() > state.last_dreamer_run.date():
            logger.dreamer("Nightly dreamer starting...")
            archive_conversation(state, config)
            prompt = build_dreamer_prompt(config)
            state.dreamer_active = True
            await queue.put((prompt, False))
            state.last_dreamer_run = now
            logger.dreamer("Dreamer prompt queued")


async def monitor_loop(queue: asyncio.Queue, *, state: vm.State, config: vm.VestaConfig) -> None:
    last_proactive = vfx.get_current_time()
    notification_buffer: list[vm.Notification] = []
    buffer_start_time = None

    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            await asyncio.sleep(config.notification_check_interval)

            if state.shutdown_event and state.shutdown_event.is_set():
                break

            now = vfx.get_current_time()

            if (now - last_proactive).total_seconds() >= config.proactive_check_interval * 60:
                await check_proactive_task(queue, config=config)
                last_proactive = now

            await process_nightly_memory(queue, state=state, config=config)

            notification_buffer, buffer_start_time = await notifs.load_and_display_new_notifications(
                notification_buffer, buffer_start_time=buffer_start_time, config=config
            )

            if notifs.should_flush_buffer(
                notification_buffer, buffer_start_time=buffer_start_time, current_time=now, buffer_delay=config.notification_buffer_delay
            ):
                await notifs.process_batch(notification_buffer, queue=queue, state=state, config=config)
                notification_buffer = []
                buffer_start_time = None
        except asyncio.CancelledError:
            break
