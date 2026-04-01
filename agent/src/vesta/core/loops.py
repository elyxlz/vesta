"""Background processing loops and notification handling."""

import asyncio
import collections
import datetime as dt
import json
import pathlib as pl

import pydantic
from claude_agent_sdk import ClaudeSDKClient, ClaudeSDKError

import vesta.models as vm
from vesta import logger
from vesta.core.client import process_message, build_client_options, attempt_interrupt, filter_tool_lines, persist_session_id, _cancel_task
from vesta.core.init import load_prompt, build_restart_context


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



async def process_notifications(*, queue: asyncio.Queue[tuple[str, bool, bool]], state: vm.State, config: vm.VestaConfig) -> None:
    new_notifs = await load_notifications(config=config)
    if not new_notifs:
        return

    suffix = load_prompt("notification_suffix", config) or ""

    for notif in new_notifs:
        logger.notification(notif.model_dump_json(indent=2))
        state.event_bus.emit({"type": "notification", "source": notif.source, "summary": notif.format_for_display()})

        # Drop WhatsApp status updates silently — zero cost
        chat_name = getattr(notif, "chat_name", "") or ""
        if chat_name == "status":
            continue

        # Buffer email notifications for batched processing
        if notif.source == "microsoft" and notif.type == "email":
            state.email_buffer.append(notif)
            continue

        prompt = notif.format_for_display()
        if suffix:
            prompt += f"\n\n{suffix}"

        event_id = getattr(notif, "event_id", "") or ""
        # Only interrupt for Lucio's messages/reactions on the main WhatsApp instance
        contact_phone = getattr(notif, "contact_phone", "") or ""
        instance = getattr(notif, "instance", "") or ""
        is_interrupt = (
            event_id.startswith("wa:")
            and contact_phone.replace(" ", "").endswith("3483826189")
            and instance == ""
        )

        if is_interrupt:
            state.interrupt_requested = True
            if state.client:
                await attempt_interrupt(state, config=config, reason="Notification interrupt")
            # Emit clean user message for webchat display
            wa_message = getattr(notif, "message", "") or ""
            if wa_message.strip():
                state.event_bus.emit({"type": "user", "text": wa_message.strip()})
            await queue.put((prompt, False, True))
        else:
            await queue.put((prompt, False, False))

    await delete_notification_files(new_notifs)


async def flush_email_buffer(*, queue: asyncio.Queue[tuple[str, bool, bool]], state: vm.State, config: vm.VestaConfig) -> None:
    """Flush buffered email notifications as a single batched prompt."""
    if not state.email_buffer:
        return

    emails = list(state.email_buffer)
    state.email_buffer.clear()

    suffix = load_prompt("notification_suffix", config) or ""

    lines = [f"[{len(emails)} email(s) received]"]
    for email in emails:
        lines.append(email.format_for_display())
    prompt = "\n".join(lines)
    if suffix:
        prompt += f"\n\n{suffix}"

    logger.notification(f"Flushing {len(emails)} batched email(s)")
    await queue.put((prompt, False, False))


async def queue_greeting(queue: asyncio.Queue[tuple[str, bool, bool]], *, config: vm.VestaConfig, reason: str) -> None:
    if reason == "first_start":
        prompt = load_prompt("first_start", config)
        if prompt:
            prompt = f"[System: your name is {config.agent_name}]\n\n{prompt}"
    else:
        prompt = build_restart_context(reason, config)
    if not prompt or not prompt.strip():
        return

    await queue.put((prompt.strip(), False, False))
    logger.startup(f"Queued {reason} greeting")


# --- Message processing ---


async def _process_message_safely(msg: str, *, is_user: bool, user_initiated: bool = False, state: vm.State, config: vm.VestaConfig) -> None:
    try:
        state.user_initiated_turn = is_user or user_initiated
        if is_user:
            logger.user(msg)
            state.event_bus.emit({"type": "user", "text": msg})
        else:
            preview = msg[:200] + "..." if len(msg) > 200 else msg
            logger.system(preview.replace("\n", " "))
        state.event_bus.set_state("thinking")
        await process_message(msg, state=state, config=config, is_user=is_user)
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


async def _process_interruptible(
    msg: str, *, is_user: bool, user_initiated: bool = False, queue: asyncio.Queue[tuple[str, bool, bool]], state: vm.State, config: vm.VestaConfig
) -> None:
    """Process a message while monitoring the queue for new messages that should interrupt."""
    pending: collections.deque[tuple[str, bool, bool]] = collections.deque([(msg, is_user, user_initiated)])
    process_task: asyncio.Task[None] | None = None

    try:
        while pending:
            if state.pending_context is not None:
                for remaining in pending:
                    await queue.put(remaining)
                break

            current_msg, current_is_user, current_user_initiated = pending.popleft()
            state.interrupt_event = asyncio.Event()
            process_task = asyncio.create_task(_process_message_safely(current_msg, is_user=current_is_user, user_initiated=current_user_initiated, state=state, config=config))

            while not process_task.done():
                queue_task: asyncio.Task[tuple[str, bool, bool]] = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({process_task, queue_task}, return_when=asyncio.FIRST_COMPLETED)

                if queue_task in done:
                    new_item = queue_task.result()
                    pending.append(new_item)
                    _, new_is_user, _ = new_item
                    if new_is_user or state.interrupt_requested:
                        state.interrupt_requested = False
                        state.interrupt_event.set()
                        logger.interrupt(f"New message queued, interrupting current processing ({len(pending)} pending)")
                        await process_task
                        break
                    # Non-interrupt notification: keep processing, handle after current finishes
                else:
                    await _cancel_task(queue_task)
            else:
                # Normal completion (not interrupted) — propagate any exception
                await process_task
            process_task = None
            state.interrupt_event = None
    except asyncio.CancelledError:
        if process_task and not process_task.done():
            process_task.cancel()
            await asyncio.gather(process_task, return_exceptions=True)
        raise


async def message_processor(queue: asyncio.Queue[tuple[str, bool, bool]], *, state: vm.State, config: vm.VestaConfig) -> None:
    while state.shutdown_event and not state.shutdown_event.is_set():
        logger.client("Creating new client session...")
        try:
            options = build_client_options(config, state)
        except FileNotFoundError as e:
            logger.shutdown(f"Fatal: could not build client options — {e}")
            state.shutdown_event.set()
            return
        async with ClaudeSDKClient(options=options) as client:
            state.client = client
            logger.client("Client session started")

            try:
                if state.pending_context:
                    await queue.put((state.pending_context, False, False))
                    state.pending_context = None

                while not state.shutdown_event.is_set() and state.pending_context is None:
                    try:
                        msg, is_user, user_initiated = await asyncio.wait_for(queue.get(), timeout=1.0)
                    except TimeoutError:
                        continue

                    await _process_interruptible(msg, is_user=is_user, user_initiated=user_initiated, queue=queue, state=state, config=config)

                    if state.dreamer_active:
                        state.dreamer_active = False
                        state.event_bus.clear_history()
                        _trigger_nightly_restart(state=state, config=config)
            finally:
                state.client = None
                state.interrupt_event = None
                logger.client("Client session closed")


# --- Proactive & dreamer ---


async def check_proactive_task(queue: asyncio.Queue[tuple[str, bool, bool]], *, config: vm.VestaConfig) -> None:
    prompt = load_prompt("proactive_check", config)
    if not prompt:
        return
    logger.proactive(f"Running {config.proactive_check_interval}-minute check...")
    await queue.put((prompt, False, False))


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


async def process_nightly_memory(queue: asyncio.Queue[tuple[str, bool, bool]], *, state: vm.State, config: vm.VestaConfig) -> None:
    if config.ephemeral:
        return

    now = _now()
    if config.nightly_memory_hour is not None and now.hour == config.nightly_memory_hour:
        if state.last_dreamer_run is None or now.date() > state.last_dreamer_run.date():
            logger.dreamer("Nightly dreamer starting...")
            prompt = load_prompt("dream", config) or ""
            if not prompt.strip():
                logger.dreamer("Empty dream prompt — skipping")
                return
            state.dreamer_active = True
            await queue.put((prompt, False, False))
            state.last_dreamer_run = now
            try:
                (config.data_dir / "last_dreamer_run").write_text(now.isoformat())
            except OSError:
                logger.warning("Could not persist last_dreamer_run")
            logger.dreamer("Dreamer prompt queued")


# --- Monitor loop ---


async def monitor_loop(queue: asyncio.Queue[tuple[str, bool, bool]], *, state: vm.State, config: vm.VestaConfig) -> None:
    notif_dir = config.notifications_dir
    notif_dir.mkdir(parents=True, exist_ok=True)

    # Process any pre-existing notifications before watching
    await process_notifications(queue=queue, state=state, config=config)

    last_proactive = _now()

    async def _watch_notifications() -> None:
        """Watch for new notification files via inotify (instant detection)."""
        try:
            from watchfiles import awatch, Change
        except ImportError:
            logger.warning("watchfiles not available, falling back to polling")
            while state.shutdown_event and not state.shutdown_event.is_set():
                await asyncio.sleep(config.notification_check_interval)
                await process_notifications(queue=queue, state=state, config=config)
            return

        logger.startup("Notification watcher started (inotify)")
        try:
            async for changes in awatch(notif_dir):
                if state.shutdown_event and state.shutdown_event.is_set():
                    break
                has_json = any(
                    change_type in (Change.added, Change.modified) and str(path).endswith(".json")
                    for change_type, path in changes
                )
                if has_json:
                    await process_notifications(queue=queue, state=state, config=config)
        except asyncio.CancelledError:
            return

    async def _periodic_checks() -> None:
        """Run proactive and dreamer checks on a timer."""
        nonlocal last_proactive
        while state.shutdown_event and not state.shutdown_event.is_set():
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                return

            if state.shutdown_event and state.shutdown_event.is_set():
                break

            now = _now()
            if (now - last_proactive).total_seconds() >= config.proactive_check_interval * 60:
                await check_proactive_task(queue, config=config)
                last_proactive = now

            await process_nightly_memory(queue, state=state, config=config)

    async def _email_flush_loop() -> None:
        """Flush batched email notifications every 60 seconds."""
        while state.shutdown_event and not state.shutdown_event.is_set():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                return
            if state.shutdown_event and state.shutdown_event.is_set():
                break
            await flush_email_buffer(queue=queue, state=state, config=config)

    watch_task = asyncio.create_task(_watch_notifications())
    timer_task = asyncio.create_task(_periodic_checks())
    email_task = asyncio.create_task(_email_flush_loop())

    try:
        await asyncio.gather(watch_task, timer_task, email_task)
    except asyncio.CancelledError:
        watch_task.cancel()
        timer_task.cancel()
        email_task.cancel()
        await asyncio.gather(watch_task, timer_task, email_task, return_exceptions=True)
