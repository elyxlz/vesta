"""Background processing loops and notification handling."""

import asyncio
import collections
import datetime as dt
import json
import pathlib as pl
import time

import pydantic
from claude_agent_sdk import ClaudeSDKClient, ClaudeSDKError
from watchfiles import awatch, Change

from . import models as vm
from . import logger
from . import config as cfg
from . import notification_interrupt_policy
from . import state_store
from . import vestad_client
from .config import DEFAULT_CONTEXT_WINDOW
from .client import (
    process_message,
    build_client_options,
    attempt_interrupt,
    persist_session_id,
    resolve_openrouter_max_tokens,
    compact_session,
    _cancel_task,
)
from .diagnostics import format_crash_detail
from .helpers import load_prompt, build_restart_context
from .openrouter_cache import start_cache_proxy
from .provider import ProviderAuthState

from .models import CORE_POOL_TYPES, CORE_SOURCE, TYPE_NIGHTLY_DREAM, TYPE_PROACTIVE_CHECK


def _now() -> dt.datetime:
    return dt.datetime.now()


# --- Notifications ---


def _load_notification_files(directory: pl.Path) -> list[tuple[pl.Path, str]]:
    if not directory.exists():
        return []
    results = []
    for f in sorted(directory.glob("*.json")):
        if not f.is_file():
            logger.warning(f"skipping non-file notification entry {f.name}")
            continue
        try:
            results.append((f, f.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError) as e:
            logger.error(f"skipping unreadable notification {f.name}: {e}")
    return results


def drop_core_notification(*, type_: str, body: str, config: vm.VestaConfig, name: str | None = None) -> pl.Path:
    """Write a `source=core` notification file. `name` is the filename stem; defaults to type+millisecond timestamp for natural ordering.

    Core notifications are exempt from the user's rules; monitor_loop derives their disposition from
    the type (see CORE_POOL_TYPES)."""
    notif = vm.Notification(timestamp=dt.datetime.now(), source=CORE_SOURCE, type=type_, body=body)
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    stem = name if name is not None else f"{type_}-{int(time.time() * 1000)}"
    path = config.notifications_dir / f"{stem}.json"
    path.write_text(notif.model_dump_json())
    return path


def _notif_interrupts(notif: vm.Notification, rules: list[notification_interrupt_policy.NotificationInterruptRule]) -> bool:
    """True if the notification preempts the current turn. Core notifications are exempt from the user's
    rules — their disposition is control-flow, derived from the type (CORE_POOL_TYPES); everything else
    goes through the ruleset (first match wins, else the producer's own interrupt default)."""
    if notif.source == CORE_SOURCE:
        return notif.type not in CORE_POOL_TYPES
    return notification_interrupt_policy.should_interrupt(notif, rules)


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
    _delete_paths([n.file_path for n in notifications if n.file_path])


_REPLY_SKILLS = frozenset({"app-chat", "whatsapp", "telegram"})


def _format_one(notif: vm.Notification) -> str:
    """Embed a reply hint inside the <notification> element so the model sees them as one unit.

    The hint points the model at the originating channel's reply skill instead of copying its CLI syntax."""
    body = notif.format_for_display()
    if notif.type != "message" or notif.source not in _REPLY_SKILLS:
        return body
    hint = f"\n→ Reply using the `{notif.source}` skill."
    return body.replace("</notification>", f"{hint}\n</notification>")


def format_notification_batch(notifications: list[vm.Notification], *, suffix: str = "") -> str:
    suffix_str = f"\n\n{suffix}" if suffix else ""
    inner = "\n".join(_format_one(n) for n in notifications)
    return f"<notifications>\n{inner}\n</notifications>{suffix_str}"


def _delete_paths(file_paths: list[str]) -> None:
    for path_str in file_paths:
        pl.Path(path_str).unlink(missing_ok=True)


async def process_batch(
    notifications: list[vm.Notification],
    *,
    queue: asyncio.Queue[vm.QueuedTurn],
    state: vm.State,
    config: vm.VestaConfig,
    external_suffix_name: str = "notification_suffix",
) -> None:
    """Render a batch as one prompt and queue it. Internal (`source=core`) notifications skip the external-message suffix; mixed batches render in two sections, system first.

    File paths are carried in the queue item and deleted only after the message is processed,
    so that a mid-compaction restart can recover unprocessed notifications from disk."""
    if not notifications:
        return

    # Don't SDK-abort a non-interruptible boot turn: the batch is still queued below and the
    # queue-watcher defers it until the boot turn completes.
    if state.client and not state.noninterruptible_turn_active:
        await attempt_interrupt(state, config=config, reason="Notification interrupt")

    system = [n for n in notifications if n.source == CORE_SOURCE]
    external = [n for n in notifications if n.source != CORE_SOURCE]

    async def queue_section(group: list[vm.Notification], *, suffix: str) -> None:
        paths = [n.file_path for n in group if n.file_path]
        await queue.put(vm.QueuedTurn(format_notification_batch(group, suffix=suffix), False, paths))

    if system:
        await queue_section(system, suffix="")
    if external:
        await queue_section(external, suffix=load_prompt(external_suffix_name, config) or "")


def greeting_turn(*, config: vm.VestaConfig, state: vm.State, reason: str) -> str | None:
    """The boot greeting as a prompt body (or None to skip): first start runs the setup prompt,
    a restart builds the wake-up context (reason + restart prompt + any pending dreamer summary).

    Delivered as a boot turn rather than a notification — it is the agent's own startup context, not
    an external event, so it never enters the interrupt-rules/pool/triage machinery."""
    if state.provider_status is None or state.provider_status.state != ProviderAuthState.AUTHENTICATED:
        logger.startup("No authenticated provider yet, waiting for sign-in before starting")
        return None

    if reason == "first_start":
        setup_prompt = load_prompt("birth", config)
        if not setup_prompt:
            # No prompt to run, flip the flag so we don't loop into first-start every reboot.
            state.persisted.first_start_done = True
            state_store.save_state(state.persisted, config)
            return None
        logger.startup("Boot turn: birth")
        return setup_prompt.strip()

    extras = []
    if state.persisted.show_dreamer_summary:
        state.persisted.show_dreamer_summary = False
        state_store.save_state(state.persisted, config)
        for path in sorted(config.dreamer_dir.glob("*.md"), reverse=True)[:3]:
            extras.append(f"[Dreamer Summary: {path.stem}]\n{path.read_text().strip()}")
    prompt = build_restart_context(reason, config, extras=extras)
    if not prompt or not prompt.strip():
        return None

    logger.startup(f"Boot turn: {reason} greeting")
    return prompt.strip()


# --- Message processing ---


async def _run_messages_with_interrupts(
    first: vm.QueuedTurn,
    *,
    queue: asyncio.Queue[vm.QueuedTurn],
    state: vm.State,
    config: vm.VestaConfig,
) -> None:
    """Run a turn and any follow-ups; new queue items interrupt the current turn (deferred during
    compaction, and never for a non-interruptible boot turn, which runs to completion)."""

    async def run_one(text: str, *, user: bool) -> None:
        try:
            if user:
                logger.user(text)
                state.event_bus.emit({"type": "user", "text": text})
            else:
                preview = text[:1000] + "..." if len(text) > 1000 else text
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
                # Belt-and-suspenders: sdk_parsing already persists the session_id from the init
                # message. The official claude_agent_sdk client has no session_id attribute, so this
                # very-early-crash fallback degrades to None rather than AttributeError-ing here.
                try:
                    sid = state.client.session_id  # ty: ignore[unresolved-attribute]
                except AttributeError:
                    sid = None
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

    pending: collections.deque[vm.QueuedTurn] = collections.deque([first])
    process_task: asyncio.Task[None] | None = None

    try:
        while pending:
            if state.graceful_shutdown.is_set():
                for remaining in pending:
                    await queue.put(remaining)
                break

            current = pending.popleft()
            # Defer (don't drive claude, don't delete the file) while unauthenticated: a dead token
            # just burns the CLI's full retry budget per message. Keeping the notification file on
            # disk means it re-runs after the user re-authenticates — which restarts the agent, so
            # monitor_loop re-reads the dir and re-queues it. (Migrations regenerate on boot anyway.)
            if state.provider_status is not None and state.provider_status.state == ProviderAuthState.NOT_AUTHENTICATED:
                logger.client("Provider not authenticated; deferring message until re-auth")
                continue
            state.interrupt_event = asyncio.Event()
            state.noninterruptible_turn_active = not current.interruptible
            process_task = asyncio.create_task(run_one(current.text, user=current.is_user))

            while not process_task.done():
                queue_task: asyncio.Task[vm.QueuedTurn] = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({process_task, queue_task}, return_when=asyncio.FIRST_COMPLETED)

                if queue_task in done:
                    pending.append(queue_task.result())
                    if not current.interruptible:
                        # Boot turns run to completion; the queued item waits its turn rather than preempting.
                        continue
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
            state.noninterruptible_turn_active = False
            # Keep the file if the turn flipped auth to not_authenticated (converse detects a
            # terminal 401/402 mid-turn): like a deferred message above, it must re-run after re-auth.
            if state.provider_status is None or state.provider_status.state == ProviderAuthState.AUTHENTICATED:
                _delete_paths(current.file_paths)
                # Tell live clients the notification cleared (file gone). Only notification turns carry
                # file_paths, so user-message turns emit nothing. notif_id is the file stem, matching
                # the arrival's NotificationEvent.notif_id.
                for path_str in current.file_paths:
                    state.event_bus.emit({"type": "notification_cleared", "notif_id": pl.Path(path_str).stem})
            process_task = None
            state.interrupt_event = None
    except asyncio.CancelledError:
        if process_task:
            await _cancel_task(process_task)
        raise
    finally:
        state.noninterruptible_turn_active = False


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
        await compact_session(state=state)
    except (ClaudeSDKError, OSError, RuntimeError, TimeoutError) as exc:
        logger.warning(f"Compaction before restart failed: {exc}, restarting anyway")
    finally:
        state.compacting = False
        state.event_bus.set_state("idle")
    # vestad owns the restart: it SIGTERMs us (clean shutdown) and starts us back, resuming the
    # compacted session. We don't set graceful_shutdown ourselves — under the on-failure policy a
    # clean self-exit would stay down. If vestad is unreachable, stay up on the compacted session.
    if not await vestad_client.request_restart():
        logger.warning("vestad unreachable for nightly restart; continuing on the compacted session")


async def message_processor(queue: asyncio.Queue[vm.QueuedTurn], *, state: vm.State, config: vm.VestaConfig) -> None:
    # An agent with no authenticated provider can't drive the model. It still boots and stays reachable
    # so vestad can deliver credentials over the API, but there is nothing to process here until sign-in
    # restarts the process with a provider applied — so idle instead of building an SDK client (which
    # requires a provider). Messages are deferred upstream while unauthenticated, so the queue stays empty.
    if state.provider_status is None or state.provider_status.state != ProviderAuthState.AUTHENTICATED:
        logger.client("No authenticated provider; idling until sign-in")
        await state.shutdown_event.wait()
        return
    logger.client("Creating new client session...")
    if isinstance(config.provider, vm.OpenRouterConfig):
        if state.openrouter_max_tokens is None:
            real_window = await resolve_openrouter_max_tokens(config)
            if real_window:
                # Cap at max_context_tokens: cache-read cost scales with how large the
                # cached prefix grows before autocompact, so big-window models default
                # to a 200k working window unless the user raises the cap.
                cap = config.provider.max_context_tokens or DEFAULT_CONTEXT_WINDOW
                state.openrouter_max_tokens = min(real_window, cap)
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
                            turn = await asyncio.wait_for(queue.get(), timeout=1.0)
                        except TimeoutError:
                            continue

                        state.processor_busy = True
                        try:
                            await _run_messages_with_interrupts(turn, queue=queue, state=state, config=config)
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
    drop_core_notification(type_=TYPE_PROACTIVE_CHECK, body=prompt, config=config)


DREAMER_CATCHUP_HOURS = 6


def process_nightly_memory(*, state: vm.State, config: vm.VestaConfig) -> None:
    """Drop a dream notification if today's dream hasn't completed yet. Caller (`monitor_loop`) rate-limits this to once an hour and we bound retries to `DREAMER_CATCHUP_HOURS` after the configured hour, so a silent failure to call `mark_dreamer_complete` retries a few times but cannot preempt the agent for the rest of the day."""
    if config.ephemeral or config.nightly_memory_hour is None:
        return
    # A brand-new agent has no history to curate; a catch-up dream firing inside the morning
    # window would compact + restart mid-onboarding. Wait until first-start has completed.
    if not state.persisted.first_start_done:
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
    drop_core_notification(type_=TYPE_NIGHTLY_DREAM, body=prompt, config=config)
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


async def monitor_loop(queue: asyncio.Queue[vm.QueuedTurn], *, state: vm.State, config: vm.VestaConfig) -> None:
    last_proactive = _now()
    # Init one hour back so the first dreamer check runs on the first tick after boot.
    last_dreamer_check = _now() - dt.timedelta(hours=1)
    pending_passive: list[vm.Notification] = []
    idle_since: dt.datetime | None = None
    # Files sent to the queue but not yet processed (and thus not yet deleted from disk).
    # Trimmed each tick to the paths that still exist; prevents re-queueing mid-compaction.
    queued_paths: set[str] = set()
    notify = asyncio.Event()

    watcher_task = asyncio.create_task(_notification_watcher(notify, notifications_dir=config.notifications_dir, shutdown=state.shutdown_event))

    try:
        while not state.shutdown_event.is_set():
            # Wait for either a file change or the periodic tick
            try:
                await asyncio.wait_for(notify.wait(), timeout=config.monitor_tick_interval)
            except TimeoutError:
                pass
            notify.clear()

            if state.shutdown_event.is_set():
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

            # Prune paths that were processed and deleted; this is how we know a queued item
            # completed and its file is gone, preventing unbounded set growth.
            queued_paths = {p for p in queued_paths if pl.Path(p).exists()}

            notifications = await load_notifications(config=config)
            rules = await asyncio.to_thread(cfg.load_notification_rules, config)
            fresh = [n for n in notifications if not n.file_path or n.file_path not in queued_paths]
            decisions = [(n, _notif_interrupts(n, rules)) for n in fresh]
            interrupt_notifs = [n for n, hot in decisions if hot]
            new_passive = [n for n, hot in decisions if not hot]

            # Emit each genuinely-new notification to the bus exactly once, enriched with structured
            # facets + the effective interrupt disposition for the history view. load_notifications
            # re-reads every file each tick, so files kept on disk (e.g. deferred while
            # unauthenticated) must not re-emit — that was the notification storm.
            for notif, hot in decisions:
                state.event_bus.emit(
                    {
                        "type": "notification",
                        "source": notif.source,
                        "summary": notif.format_for_display(),
                        "notif_type": notif.type,
                        "sender": notification_interrupt_policy.notif_sender(notif) or "",
                        "fields": notification_interrupt_policy.notif_facet_fields(notif),
                        "decided": "interrupt" if hot else "pool",
                        "notif_id": pl.Path(notif.file_path).stem if notif.file_path else "",
                    }
                )

            queued_paths.update(n.file_path for n in fresh if n.file_path)
            pending_passive.extend(new_passive)

            if interrupt_notifs:
                await process_batch(interrupt_notifs, queue=queue, state=state, config=config)

            # Track how long the agent has been continuously idle; micro-gaps shorter than the
            # grace never qualify, so a brief breather between turns doesn't trigger a triage pass.
            if state.event_bus.state == "idle":
                if idle_since is None:
                    idle_since = now
            else:
                idle_since = None

            if pending_passive and idle_since is not None and (now - idle_since).total_seconds() >= config.notif_pool_idle_grace_seconds:
                await process_batch(pending_passive, queue=queue, state=state, config=config, external_suffix_name="notification_triage")
                pending_passive = []
    finally:
        await _cancel_task(watcher_task)
