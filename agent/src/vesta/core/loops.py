"""Background processing loops and notification handling."""

import asyncio
import datetime as dt
import json
import pathlib as pl

import pydantic
from claude_agent_sdk import ClaudeSDKClient, ClaudeSDKError

import vesta.models as vm
from vesta import logger
from vesta.core.client import process_message, build_client_options, attempt_interrupt, filter_tool_lines, persist_session_id
from vesta.core.init import get_memory_path, load_prompt, build_restart_context


def _now() -> dt.datetime:
    return dt.datetime.now()


# --- Notifications ---


def _load_notification_files(directory: pl.Path) -> list[tuple[pl.Path, str]]:
    if not directory.exists():
        return []
    return [(f, f.read_text(encoding="utf-8")) for f in directory.glob("*.json")]


async def load_notifications(*, config: vm.VestaConfig) -> list[vm.Notification]:
    file_contents = _load_notification_files(config.notifications_dir)

    notifications = []
    for file, content in file_contents:
        try:
            data = json.loads(content)
            notif = vm.Notification(**data)
            notif.file_path = str(file)
            notifications.append(notif)
        except (json.JSONDecodeError, pydantic.ValidationError, KeyError, TypeError) as e:
            logger.error(f"Failed to parse notification {file.name}: {e}")
            file.unlink(missing_ok=True)

    return notifications


async def delete_notification_files(notifications: list[vm.Notification]) -> None:
    paths = {n.file_path for n in notifications if n.file_path}
    for path_str in paths:
        pl.Path(path_str).unlink(missing_ok=True)


def format_notification_batch(notifications: list[vm.Notification], *, suffix: str = "") -> str:
    suffix_str = f"\n\n{suffix}" if suffix else ""
    if len(notifications) == 1:
        return notifications[0].format_for_display() + suffix_str

    prompts = [n.format_for_display() for n in notifications]
    return "[NOTIFICATIONS]\n" + "\n".join(prompts) + suffix_str


async def load_and_display_new_notifications(
    notification_buffer: list[vm.Notification], *, buffer_start_time: dt.datetime | None, state: vm.State, config: vm.VestaConfig
) -> tuple[list[vm.Notification], dt.datetime | None]:
    new_notifs = await load_notifications(config=config)

    if new_notifs:
        existing_paths = {n.file_path for n in notification_buffer if n.file_path}
        truly_new = [n for n in new_notifs if n.file_path not in existing_paths]

        if truly_new:
            notification_buffer.extend(truly_new)
            now = dt.datetime.now()
            if buffer_start_time is None:
                buffer_start_time = now

            for notif in truly_new:
                logger.notification(notif.model_dump_json(indent=2))
                state.event_bus.emit({"type": "notification", "source": notif.source, "summary": notif.format_for_display()})

    return notification_buffer, buffer_start_time


async def process_batch(notifications: list[vm.Notification], *, queue: asyncio.Queue[tuple[str, bool]], state: vm.State, config: vm.VestaConfig) -> None:
    if not notifications:
        return

    suffix = load_prompt("notification_suffix", config) or ""
    prompt = format_notification_batch(notifications, suffix=suffix)

    if state.client:
        await attempt_interrupt(state, config=config, reason="Notification interrupt")

    await queue.put((prompt, False))
    await delete_notification_files(notifications)


async def queue_greeting(queue: asyncio.Queue[tuple[str, bool]], *, config: vm.VestaConfig, reason: str) -> None:
    if reason == "first_start":
        prompt = load_prompt("first_start", config)
    else:
        prompt = build_restart_context(reason, config)
    if not prompt or not prompt.strip():
        return

    await queue.put((prompt.strip(), False))
    logger.startup(f"Queued {reason} greeting")


# --- Message processing ---


def build_dreamer_prompt(config: vm.VestaConfig) -> str:
    content = load_prompt("dreamer", config) or ""
    return content.format(
        memory_path=get_memory_path(config),
        skills_dir=config.skills_dir,
        prompts_dir=config.prompts_dir,
        dreamer_dir=config.dreamer_dir,
        install_root=config.install_root,
        repo_root=config.repo_root,
    )


async def _process_message_safely(msg: str, *, is_user: bool, state: vm.State, config: vm.VestaConfig) -> None:
    try:
        if is_user:
            state.event_bus.emit({"type": "user", "text": msg})
        else:
            preview = msg[:200] + "..." if len(msg) > 200 else msg
            logger.system(preview.replace("\n", " "))
        state.event_bus.set_state("thinking")
        responses, _ = await process_message(msg, state=state, config=config, is_user=is_user)
        for response in responses:
            if not response or not response.strip():
                continue
            filtered = filter_tool_lines(response)
            if filtered:
                logger.assistant(filtered)
                state.event_bus.emit({"type": "assistant", "text": filtered})
    except (ClaudeSDKError, OSError, RuntimeError, ValueError, TimeoutError) as e:
        if isinstance(e, TimeoutError):
            error_msg = "Response timed out"
        else:
            error_msg = str(e) or type(e).__name__
        if not state.session_id and state.client:
            try:
                sid = state.client.session_id  # type: ignore[attr-defined]
                if sid:
                    persist_session_id(sid, state=state, config=config)
            except (AttributeError, TypeError):
                pass
        logger.error(f"Error processing message: {error_msg}")
        state.event_bus.emit({"type": "error", "text": error_msg})
        state.pending_context = f"[System: Previous request failed with error: {error_msg}. Session was reset.]"
    finally:
        state.event_bus.set_state("idle")


async def message_processor(queue: asyncio.Queue[tuple[str, bool]], *, state: vm.State, config: vm.VestaConfig) -> None:
    while state.shutdown_event and not state.shutdown_event.is_set():
        logger.client("Creating new client session...")
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client:
            state.client = client
            logger.client("Client session started")

            try:
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
                        state.event_bus.clear_history()
                        _trigger_nightly_restart(state=state, config=config)
            finally:
                state.client = None
                logger.client("Client session closed")


# --- Proactive & dreamer ---


async def check_proactive_task(queue: asyncio.Queue[tuple[str, bool]], *, config: vm.VestaConfig) -> None:
    prompt = load_prompt("proactive_check", config)
    if not prompt:
        return
    prompt = prompt.replace("{proactive_check_interval}", str(config.proactive_check_interval))
    logger.proactive(f"Running {config.proactive_check_interval}-minute check...")
    await queue.put((prompt, False))


def _trigger_nightly_restart(*, state: vm.State, config: vm.VestaConfig) -> None:
    logger.dreamer("Dreamer complete, triggering nightly restart...")
    state.session_id = None
    config.session_file.unlink(missing_ok=True)

    today = _now().strftime("%Y-%m-%d")
    summary_path = config.dreamer_dir / f"{today}.md"
    extras = []
    if summary_path.exists():
        extras.append(f"[Dreamer Summary]\n{summary_path.read_text().strip()}")

    state.pending_context = build_restart_context("new day — conversation history reset, nightly dreamer ran", config, extras=extras)


async def process_nightly_memory(queue: asyncio.Queue[tuple[str, bool]], *, state: vm.State, config: vm.VestaConfig) -> None:
    if config.ephemeral:
        return

    now = _now()
    if config.nightly_memory_hour is not None and now.hour == config.nightly_memory_hour:
        if state.last_dreamer_run is None or now.date() > state.last_dreamer_run.date():
            logger.dreamer("Nightly dreamer starting...")
            prompt = build_dreamer_prompt(config)
            state.dreamer_active = True
            await queue.put((prompt, False))
            state.last_dreamer_run = now
            try:
                (config.data_dir / "last_dreamer_run").write_text(now.isoformat())
            except OSError:
                logger.warning("Could not persist last_dreamer_run")
            logger.dreamer("Dreamer prompt queued")


# --- Monitor loop ---


async def monitor_loop(queue: asyncio.Queue[tuple[str, bool]], *, state: vm.State, config: vm.VestaConfig) -> None:
    last_proactive = _now()
    notification_buffer: list[vm.Notification] = []
    buffer_start_time: dt.datetime | None = None

    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            await asyncio.sleep(config.notification_check_interval)

            if state.shutdown_event and state.shutdown_event.is_set():
                break

            now = _now()

            if (now - last_proactive).total_seconds() >= config.proactive_check_interval * 60:
                await check_proactive_task(queue, config=config)
                last_proactive = now

            await process_nightly_memory(queue, state=state, config=config)

            notification_buffer, buffer_start_time = await load_and_display_new_notifications(
                notification_buffer, buffer_start_time=buffer_start_time, state=state, config=config
            )

            if notification_buffer and buffer_start_time and (now - buffer_start_time).total_seconds() >= config.notification_buffer_delay:
                await process_batch(notification_buffer, queue=queue, state=state, config=config)
                notification_buffer = []
                buffer_start_time = None
        except asyncio.CancelledError:
            break
