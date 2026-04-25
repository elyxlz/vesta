"""Background processing loops and notification handling."""

import asyncio
import collections
import datetime as dt
import json
import pathlib as pl

import pydantic
from claude_agent_sdk import ClaudeSDKClient, ClaudeSDKError
from watchfiles import awatch, Change

from . import models as vm
from . import logger
from .client import process_message, build_client_options, attempt_interrupt, persist_session_id, format_crash_detail, _cancel_task
from .helpers import load_prompt, build_restart_context


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


def _reply_hint(notif: vm.Notification) -> str:
    """Inline command hint so the model invokes the reply skill instead of forgetting."""
    if notif.type != "message":
        return ""
    if notif.source == "app-chat":
        return "\n→ Reply with: `app-chat send --message '...'`"
    if notif.source in ("whatsapp", "telegram"):
        data = notif.model_dump(exclude={"file_path", "type", "source", "interrupt", "timestamp"})
        recipient = None
        for key in ("chat_name", "contact_name"):
            if key in data and data[key]:
                recipient = data[key]
                break
        if not recipient:
            return ""
        if notif.source == "whatsapp":
            return f"\n→ Reply with: `whatsapp send --to '{recipient}' --message '...'`"
        return f"\n→ Reply with: `telegram send '{recipient}' '...'`"
    return ""


def _format_one(notif: vm.Notification) -> str:
    """Embed the reply hint inside the <notification> element so the model sees them as one unit."""
    body = notif.format_for_display()
    hint = _reply_hint(notif)
    if not hint:
        return body
    return body.replace("</notification>", f"{hint}\n</notification>")


def format_notification_batch(notifications: list[vm.Notification], *, suffix: str = "") -> str:
    suffix_str = f"\n\n{suffix}" if suffix else ""
    inner = "\n".join(_format_one(n) for n in notifications)
    return f"<notifications>\n{inner}\n</notifications>{suffix_str}"


async def load_new_notifications(*, state: vm.State, config: vm.VestaConfig) -> list[vm.Notification]:
    notifications = await load_notifications(config=config)
    for notif in notifications:
        state.event_bus.emit({"type": "notification", "source": notif.source, "summary": notif.format_for_display()})
    return notifications


async def process_batch(
    notifications: list[vm.Notification], *, queue: asyncio.Queue[tuple[str, bool]], state: vm.State, config: vm.VestaConfig
) -> None:
    if not notifications:
        return

    suffix = load_prompt("notification_suffix", config) or ""
    prompt = format_notification_batch(notifications, suffix=suffix)

    if state.client:
        await attempt_interrupt(state, config=config, reason="Notification interrupt")

    await queue.put((prompt, False))
    await delete_notification_files(notifications)


CREDENTIALS_PATH = pl.Path("/root/.claude/.credentials.json")


async def queue_greeting(queue: asyncio.Queue[tuple[str, bool]], *, config: vm.VestaConfig, state: vm.State, reason: str) -> bool:
    """Returns True if a startup prompt was queued."""
    if not CREDENTIALS_PATH.exists():
        logger.startup("No credentials yet — waiting for auth before starting")
        return False

    if reason == "first_start":
        # Always mark first-start as handled, even if the prompt is missing —
        # otherwise the agent re-enters first-start on every reboot.
        (config.data_dir / "first_start_done").write_text("1")
        setup_prompt = load_prompt("first_start_setup", config)
        if setup_prompt:
            combined = f"[System: your name is {config.agent_name}]\n\n{setup_prompt.strip()}"
            await queue.put((combined, False))
            logger.startup("Queued first_start setup")
            return True
        return False

    extras = []
    flag = config.data_dir / "show_dreamer_summary"
    if flag.exists():
        flag.unlink()
        for path in sorted(config.dreamer_dir.glob("*.md"), reverse=True)[:3]:
            extras.append(f"[Dreamer Summary — {path.stem}]\n{path.read_text().strip()}")
    prompt = build_restart_context(reason, config, extras=extras)
    if not prompt or not prompt.strip():
        return False

    await queue.put((prompt.strip(), False))
    logger.startup(f"Queued {reason} greeting")
    return True


# --- Message processing ---


async def _process_message_safely(msg: str, *, is_user: bool, state: vm.State, config: vm.VestaConfig) -> None:
    try:
        if is_user:
            logger.user(msg)
            state.event_bus.emit({"type": "user", "text": msg})
        else:
            preview = msg[:200] + "..." if len(msg) > 200 else msg
            logger.system(preview.replace("\n", " "))
        state.event_bus.set_state("thinking")
        await process_message(msg, state=state, config=config, is_user=is_user)
    except asyncio.CancelledError:
        if state.shutdown_event.is_set() or state.graceful_shutdown.is_set():
            raise
        logger.error("Message processing cancelled unexpectedly — triggering restart")
        state.event_bus.emit({"type": "error", "text": "processing cancelled"})
        state.restart_reason = vm.PROCESSING_CANCELLED_ERROR
        state.graceful_shutdown.set()
        raise
    except (ClaudeSDKError, OSError, RuntimeError, ValueError, TimeoutError) as e:
        if isinstance(e, TimeoutError):
            error_msg = "Response timed out"
        else:
            error_msg = str(e) or type(e).__name__
        if not state.session_id and state.client:
            try:
                sid = state.client.session_id  # ty: ignore[unresolved-attribute]
                if sid:
                    persist_session_id(sid, state=state, config=config)
            except (AttributeError, TypeError):
                pass
        exit_code, stderr_tail = format_crash_detail(e, state.stderr_buffer, fallback="")
        detail = f"Error processing message: {error_msg} | exit_code={exit_code}"
        if stderr_tail:
            detail += f"\nRecent stderr:\n{stderr_tail}"
        logger.error(f"{detail} — triggering restart")
        state.event_bus.emit({"type": "error", "text": error_msg})
        state.restart_reason = f"error — {error_msg}"
        state.graceful_shutdown.set()
    finally:
        state.event_bus.set_state("idle")


async def _process_interruptible(
    msg: str, *, is_user: bool, queue: asyncio.Queue[tuple[str, bool]], state: vm.State, config: vm.VestaConfig
) -> None:
    """Process a message while monitoring the queue for new messages that should interrupt."""
    pending: collections.deque[tuple[str, bool]] = collections.deque([(msg, is_user)])
    process_task: asyncio.Task[None] | None = None

    try:
        while pending:
            if state.graceful_shutdown.is_set():
                for remaining in pending:
                    await queue.put(remaining)
                break

            current_msg, current_is_user = pending.popleft()
            state.interrupt_event = asyncio.Event()
            process_task = asyncio.create_task(_process_message_safely(current_msg, is_user=current_is_user, state=state, config=config))

            while not process_task.done():
                queue_task: asyncio.Task[tuple[str, bool]] = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({process_task, queue_task}, return_when=asyncio.FIRST_COMPLETED)

                if queue_task in done:
                    pending.append(queue_task.result())
                    state.interrupt_event.set()
                    logger.client(f"Interrupting: new message queued ({len(pending)} pending)")
                    await process_task
                    break
                else:
                    await _cancel_task(queue_task)

            await process_task
            process_task = None
            state.interrupt_event = None
    except asyncio.CancelledError:
        if process_task and not process_task.done():
            process_task.cancel()
            await asyncio.gather(process_task, return_exceptions=True)
        raise


async def message_processor(queue: asyncio.Queue[tuple[str, bool]], *, state: vm.State, config: vm.VestaConfig) -> None:
    logger.client("Creating new client session...")
    options = build_client_options(config, state)
    retried = False
    while True:
        try:
            async with ClaudeSDKClient(options=options) as client:
                state.client = client
                logger.client("Client session started")

                try:
                    while not state.shutdown_event.is_set():
                        try:
                            msg, is_user = await asyncio.wait_for(queue.get(), timeout=1.0)
                        except TimeoutError:
                            continue

                        await _process_interruptible(msg, is_user=is_user, queue=queue, state=state, config=config)

                        if not state.first_setup_complete.is_set():
                            state.first_setup_complete.set()
                            logger.startup("Agent ready")

                        if state.dreamer_active:
                            state.dreamer_active = False
                            logger.dreamer("Dreamer complete, clearing session for fresh context...")
                            config.session_file.unlink(missing_ok=True)
                            state.session_id = None
                            (config.data_dir / "show_dreamer_summary").write_text("1")
                            if state.last_dreamer_run is not None:
                                try:
                                    (config.data_dir / "last_dreamer_run").write_text(state.last_dreamer_run.isoformat())
                                except OSError:
                                    logger.warning("Could not persist last_dreamer_run")
                            state.restart_reason = vm.NIGHTLY_RESTART
                            state.graceful_shutdown.set()
                finally:
                    state.client = None
                    state.interrupt_event = None
                    logger.client("Client session closed")
            break
        except (ClaudeSDKError, OSError, RuntimeError) as exc:
            if retried or not state.session_id:
                raise
            await asyncio.sleep(0.05)  # give stderr handler time to drain buffered subprocess output
            exit_code, stderr_tail = format_crash_detail(exc, state.stderr_buffer)
            logger.warning(
                f"Session resume failed ({state.session_id[:16]}...): {type(exc).__name__}: {exc}"
                f" | exit_code={exit_code}"
                f" — starting fresh\nRecent stderr:\n{stderr_tail}"
            )
            state.session_id = None
            state.stderr_buffer.clear()
            config.session_file.unlink(missing_ok=True)
            options = build_client_options(config, state)
            retried = True


# --- Proactive & dreamer ---


async def check_proactive_task(queue: asyncio.Queue[tuple[str, bool]], *, config: vm.VestaConfig) -> None:
    prompt = load_prompt("proactive_check", config)
    if not prompt:
        return
    pending = queue.qsize()
    suffix = f" (queue={pending} pending — processor may be stuck)" if pending > 0 else ""
    logger.proactive(f"Running {config.proactive_check_interval}-minute check...{suffix}")
    await queue.put((prompt, False))


async def process_nightly_memory(queue: asyncio.Queue[tuple[str, bool]], *, state: vm.State, config: vm.VestaConfig) -> None:
    if config.ephemeral:
        return

    now = _now()
    if config.nightly_memory_hour is not None and now.hour == config.nightly_memory_hour:
        if state.last_dreamer_run is None or now.date() > state.last_dreamer_run.date():
            logger.dreamer("Nightly dreamer starting...")
            prompt = load_prompt("nightly_dream", config) or ""
            state.dreamer_active = True
            await queue.put((prompt, False))
            state.last_dreamer_run = now
            logger.dreamer("Dreamer prompt queued")


# --- Monitor loop ---


def _is_new_json(change: Change, path: str) -> bool:
    return change != Change.deleted and path.endswith(".json")


async def _notification_watcher(notify: asyncio.Event, *, notifications_dir: pl.Path, stop: asyncio.Event) -> None:
    """Watch the notifications directory for new .json files and signal the monitor loop."""
    async for _ in awatch(notifications_dir, stop_event=stop, recursive=False, debounce=100, watch_filter=_is_new_json):
        notify.set()


async def monitor_loop(queue: asyncio.Queue[tuple[str, bool]], *, state: vm.State, config: vm.VestaConfig) -> None:
    last_proactive = _now()
    pending_passive: list[vm.Notification] = []
    notify = asyncio.Event()

    watcher_task = asyncio.create_task(_notification_watcher(notify, notifications_dir=config.notifications_dir, stop=state.shutdown_event))

    try:
        while state.shutdown_event and not state.shutdown_event.is_set():
            try:
                # Wait for either a file change or the periodic tick
                try:
                    await asyncio.wait_for(notify.wait(), timeout=config.monitor_tick_interval)
                except TimeoutError:
                    pass
                notify.clear()

                if state.shutdown_event and state.shutdown_event.is_set():
                    break

                now = _now()

                if (now - last_proactive).total_seconds() >= config.proactive_check_interval * 60:
                    await check_proactive_task(queue, config=config)
                    last_proactive = now

                await process_nightly_memory(queue, state=state, config=config)

                notifications = await load_new_notifications(state=state, config=config)
                interrupt_notifs = [n for n in notifications if n.interrupt]
                # Passive files stay on disk until the batch flushes, so reloads would duplicate.
                queued_paths = {n.file_path for n in pending_passive if n.file_path}
                pending_passive.extend(n for n in notifications if not n.interrupt and (not n.file_path or n.file_path not in queued_paths))

                if interrupt_notifs:
                    await process_batch(interrupt_notifs, queue=queue, state=state, config=config)

                if pending_passive and state.event_bus.state == "idle":
                    await process_batch(pending_passive, queue=queue, state=state, config=config)
                    pending_passive = []
            except asyncio.CancelledError:
                break
    finally:
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass
