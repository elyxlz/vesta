"""Background processing loops and notification handling."""

import asyncio
import collections
import datetime as dt
import json
import pathlib as pl
import time

import pydantic
from core.cc_sdk import ClaudeSDKClient, ClaudeSDKError
from watchfiles import awatch, Change

from . import models as vm
from . import logger
from . import state_store
from .client import process_message, build_client_options, attempt_interrupt, persist_session_id, resolve_openrouter_max_tokens, _cancel_task
from .diagnostics import format_crash_detail
from .helpers import load_prompt, build_restart_context
from .openrouter_cache import start_cache_proxy
from .provider import CREDENTIALS_PATH

from .models import CORE_SOURCE, TYPE_FIRST_START_SETUP, TYPE_NIGHTLY_DREAM, TYPE_PROACTIVE_CHECK, TYPE_RESTART_GREETING


def _now() -> dt.datetime:
    return dt.datetime.now()


# --- Notifications ---


def _load_notification_files(directory: pl.Path) -> list[tuple[pl.Path, str]]:
    if not directory.exists():
        return []
    return [(f, f.read_text(encoding="utf-8")) for f in sorted(directory.glob("*.json"))]


def drop_core_notification(*, type_: str, body: str, interrupt: bool, config: vm.VestaConfig, name: str | None = None) -> pl.Path:
    """Write a `source=core` notification file. `name` is the filename stem; defaults to type+millisecond timestamp for natural ordering."""
    notif = vm.Notification(timestamp=dt.datetime.now(), source=CORE_SOURCE, type=type_, interrupt=interrupt, body=body)
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    stem = name if name is not None else f"{type_}-{int(time.time() * 1000)}"
    path = config.notifications_dir / f"{stem}.json"
    path.write_text(notif.model_dump_json())
    return path


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
    """Render a batch as one prompt and queue it. Internal (`source=core`) notifications skip the external-message suffix; mixed batches render in two sections, system first."""
    if not notifications:
        return

    if state.client:
        await attempt_interrupt(state, config=config, reason="Notification interrupt")

    system = [n for n in notifications if n.source == CORE_SOURCE]
    external = [n for n in notifications if n.source != CORE_SOURCE]

    if system:
        await queue.put((format_notification_batch(system, suffix=""), False))
    if external:
        suffix = load_prompt("notification_suffix", config) or ""
        await queue.put((format_notification_batch(external, suffix=suffix), False))

    await delete_notification_files(notifications)


def drop_greeting_notification(*, config: vm.VestaConfig, state: vm.State, reason: str) -> bool:
    """Drop a greeting notification (first_start_setup interrupting, restart greeting passive). Returns True if a notification was dropped."""
    if config.agent_provider == "claude" and not CREDENTIALS_PATH.exists():
        logger.startup("No credentials yet, waiting for auth before starting")
        return False

    if reason == "first_start":
        setup_prompt = load_prompt("first_start_setup", config)
        if not setup_prompt:
            # No prompt to run, flip the flag so we don't loop into first-start every reboot.
            state.persisted.first_start_done = True
            state_store.save_state(state.persisted, config)
            return False
        body = f"[System: your name is {config.agent_name}]\n\n{setup_prompt.strip()}"
        drop_core_notification(type_=TYPE_FIRST_START_SETUP, body=body, interrupt=True, config=config)
        logger.startup("Dropped first_start_setup notification")
        return True

    extras = []
    if state.persisted.show_dreamer_summary:
        state.persisted.show_dreamer_summary = False
        state_store.save_state(state.persisted, config)
        for path in sorted(config.dreamer_dir.glob("*.md"), reverse=True)[:3]:
            extras.append(f"[Dreamer Summary: {path.stem}]\n{path.read_text().strip()}")
    prompt = build_restart_context(reason, config, extras=extras)
    if not prompt or not prompt.strip():
        return False

    drop_core_notification(type_=TYPE_RESTART_GREETING, body=prompt.strip(), interrupt=False, config=config)
    logger.startup(f"Dropped {reason} greeting notification")
    return True


# --- Message processing ---


async def _run_messages_with_interrupts(
    msg: str, *, is_user: bool, queue: asyncio.Queue[tuple[str, bool]], state: vm.State, config: vm.VestaConfig
) -> None:
    """Run a message and any follow-ups; new queue items interrupt the current turn (deferred during compaction)."""

    async def run_one(text: str, *, user: bool) -> None:
        try:
            if user:
                logger.user(text)
                state.event_bus.emit({"type": "user", "text": text})
            else:
                preview = text[:200] + "..." if len(text) > 200 else text
                logger.system(preview.replace("\n", " "))
            state.event_bus.set_state("thinking")
            await process_message(text, state=state, config=config, is_user=user)
        except asyncio.CancelledError:
            if state.shutdown_event.is_set() or state.graceful_shutdown.is_set():
                raise
            logger.error("Message processing cancelled unexpectedly, triggering restart")
            state.event_bus.emit({"type": "error", "text": "processing cancelled"})
            state.persisted.last_restart_reason = "error: processing cancelled"
            state_store.save_state(state.persisted, config)
            state.graceful_shutdown.set()
            raise
        except (ClaudeSDKError, OSError, RuntimeError, ValueError, TimeoutError) as e:
            error_msg = "Response timed out" if isinstance(e, TimeoutError) else (str(e) or type(e).__name__)
            if not state.persisted.session_id and state.client:
                sid = state.client.session_id
                if sid:
                    persist_session_id(sid, state=state, config=config)
            exit_code, stderr_tail = format_crash_detail(e, state.stderr_buffer, fallback="")
            detail = f"Error processing message: {error_msg} | exit_code={exit_code}"
            if stderr_tail:
                detail += f"\nRecent stderr:\n{stderr_tail}"
            logger.error(f"{detail}, triggering restart")
            state.event_bus.emit({"type": "error", "text": error_msg})
            state.persisted.last_restart_reason = f"error: {error_msg}"
            state_store.save_state(state.persisted, config)
            state.graceful_shutdown.set()
        finally:
            state.event_bus.set_state("idle")

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
            process_task = asyncio.create_task(run_one(current_msg, user=current_is_user))

            while not process_task.done():
                queue_task: asyncio.Task[tuple[str, bool]] = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({process_task, queue_task}, return_when=asyncio.FIRST_COMPLETED)

                if queue_task in done:
                    pending.append(queue_task.result())
                    if state.compacting:
                        logger.client(f"Compaction in flight, deferring interrupt ({len(pending)} pending)")
                        continue
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


async def compact_then_restart_if_requested(*, state: vm.State) -> None:
    """If the dreamer flagged it, compact the live session at idle, then trigger the restart.

    Called between turns (right after one completes) because /compact only works while the
    session is idle. The session_id is kept, so the restart resumes the compacted conversation
    instead of starting blank. A compaction failure is logged, not fatal: we restart regardless,
    and resume still works on the un-compacted session."""
    if not state.compact_then_restart or state.client is None:
        return
    state.compact_then_restart = False
    logger.client("Compacting session before nightly restart...")
    state.event_bus.set_state("thinking")
    state.compacting = True
    try:
        await state.client.compact()
    except (ClaudeSDKError, OSError, RuntimeError) as exc:
        logger.warning(f"Compaction before restart failed: {exc} — restarting anyway")
    finally:
        state.compacting = False
        state.event_bus.set_state("idle")
    state.graceful_shutdown.set()


async def message_processor(queue: asyncio.Queue[tuple[str, bool]], *, state: vm.State, config: vm.VestaConfig) -> None:
    logger.client("Creating new client session...")
    if config.agent_provider == "openrouter":
        if state.openrouter_max_tokens is None:
            real_window = await resolve_openrouter_max_tokens(config)
            if real_window:
                # Cap at MAX_CONTEXT_TOKENS: cache-read cost scales with how large the
                # cached prefix grows before autocompact, so big-window models default
                # to a 200k working window unless the user raises the cap.
                state.openrouter_max_tokens = min(real_window, config.max_context_tokens)
                capped = f" (model supports {real_window:,})" if real_window > state.openrouter_max_tokens else ""
                logger.startup(f"OpenRouter context window: {state.openrouter_max_tokens:,} tokens{capped}")
        if state.openrouter_proxy_url is None:
            await start_cache_proxy(config, state)
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

                        state.processor_busy = True
                        try:
                            await _run_messages_with_interrupts(msg, is_user=is_user, queue=queue, state=state, config=config)
                            await compact_then_restart_if_requested(state=state)
                        finally:
                            state.processor_busy = False
                finally:
                    state.client = None
                    state.interrupt_event = None
                    state.compacting = False
                    logger.client("Client session closed")
            break
        except (ClaudeSDKError, OSError, RuntimeError) as exc:
            if retried or not state.persisted.session_id:
                raise
            await asyncio.sleep(0.05)  # give stderr handler time to drain buffered subprocess output
            exit_code, stderr_tail = format_crash_detail(exc, state.stderr_buffer)
            logger.warning(
                f"Session resume failed ({state.persisted.session_id[:16]}...): {type(exc).__name__}: {exc}"
                f" | exit_code={exit_code}"
                f", starting fresh\nRecent stderr:\n{stderr_tail}"
            )
            state.persisted.session_id = None
            state_store.save_state(state.persisted, config)
            state.stderr_buffer.clear()
            options = build_client_options(config, state)
            retried = True


# --- Proactive & dreamer ---


def check_proactive_task(*, config: vm.VestaConfig) -> None:
    prompt = load_prompt("proactive_check", config)
    if not prompt:
        return
    logger.proactive(f"Running {config.proactive_check_interval}-minute check...")
    drop_core_notification(type_=TYPE_PROACTIVE_CHECK, body=prompt, interrupt=False, config=config)


DREAMER_CATCHUP_HOURS = 6


def process_nightly_memory(*, state: vm.State, config: vm.VestaConfig) -> None:
    """Drop a dream notification if today's dream hasn't completed yet. Caller (`monitor_loop`) rate-limits this to once an hour and we bound retries to `DREAMER_CATCHUP_HOURS` after the configured hour, so a silent failure to call `mark_dreamer_complete` retries a few times but cannot preempt the agent for the rest of the day."""
    if config.ephemeral or config.nightly_memory_hour is None:
        return
    now = _now()
    # Circular window so a late hour (e.g. 22:00) still catches up past midnight.
    hours_since_start = (now.hour - config.nightly_memory_hour) % 24
    if hours_since_start >= DREAMER_CATCHUP_HOURS:
        return
    last = state.persisted.last_dreamer_run
    if last is not None and last.date() >= now.date():
        return
    logger.dreamer("Nightly dreamer starting...")
    prompt = load_prompt("nightly_dream", config) or ""
    drop_core_notification(type_=TYPE_NIGHTLY_DREAM, body=prompt, interrupt=False, config=config)
    logger.dreamer("Dreamer notification dropped")


# --- Monitor loop ---


def _is_new_json(change: Change, path: str) -> bool:
    return change != Change.deleted and path.endswith(".json")


async def _notification_watcher(notify: asyncio.Event, *, notifications_dir: pl.Path, shutdown: asyncio.Event) -> None:
    """Watch the notifications directory for new .json files and signal the monitor loop.

    watchfiles SETS the stop_event it is handed when its watch thread is torn down, so we never pass the shared
    shutdown_event directly: any watcher exception would then flip shutdown_event and wedge the whole process
    silently. We hand awatch a local event and bridge the shared shutdown_event into it instead."""
    local_stop = asyncio.Event()

    async def _bridge() -> None:
        await shutdown.wait()
        local_stop.set()

    bridge_task = asyncio.create_task(_bridge())
    try:
        async for _ in awatch(notifications_dir, stop_event=local_stop, recursive=False, debounce=100, watch_filter=_is_new_json):
            notify.set()
    finally:
        bridge_task.cancel()


async def monitor_loop(queue: asyncio.Queue[tuple[str, bool]], *, state: vm.State, config: vm.VestaConfig) -> None:
    last_proactive = _now()
    # Init one hour back so the first dreamer check runs on the first tick after boot.
    last_dreamer_check = _now() - dt.timedelta(hours=1)
    pending_passive: list[vm.Notification] = []
    notify = asyncio.Event()

    watcher_task = asyncio.create_task(_notification_watcher(notify, notifications_dir=config.notifications_dir, shutdown=state.shutdown_event))

    try:
        while state.shutdown_event and not state.shutdown_event.is_set():
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
                last_proactive = now
                if state.processor_busy or not queue.empty():
                    logger.debug("Proactive check skipped: agent is busy, waiting full interval")
                else:
                    check_proactive_task(config=config)

            if (now - last_dreamer_check).total_seconds() >= 3600:
                process_nightly_memory(state=state, config=config)
                last_dreamer_check = now

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
    finally:
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass
