"""Background processing loops and notification handling."""

import asyncio
import datetime as dt
import json
import pathlib as pl
import time
import typing as tp

import pydantic
from watchfiles import awatch, Change

from . import models as vm
from . import logger
from . import config as cfg
from . import notification_interrupt_policy
from . import state_store
from . import vestad_client
from .config import DEFAULT_CONTEXT_WINDOW
from .client import (
    SDK_ERRORS,
    process_message,
    attempt_interrupt,
    send_preempt,
    resolve_openrouter_max_tokens,
    compact_session,
    client_session,
    cancel_task,
    QueryNotDelivered,
)
from .diagnostics import format_crash_detail
from .helpers import load_prompt, build_restart_context, clear_notifications
from .notification import CORE_POOL_TYPES, CORE_SOURCE, Notification, TYPE_COMPACTION_FOLLOWUP, TYPE_NIGHTLY_DREAM, TYPE_PROACTIVE_CHECK
from .openrouter_cache import start_cache_proxy
from .provider import ProviderAuthState, is_unauthenticated


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


def drop_core_notification(*, type_: str, body: str, config: cfg.VestaConfig, name: str | None = None) -> pl.Path:
    """Write a `source=core` notification file. `name` is the filename stem; defaults to type+millisecond timestamp for natural ordering.

    Core notifications are exempt from the user's rules; monitor_loop derives their disposition from
    the type (see CORE_POOL_TYPES)."""
    notif = Notification(timestamp=dt.datetime.now(), source=CORE_SOURCE, type=type_, body=body)
    stem = name if name is not None else f"{type_}-{int(time.time() * 1000)}"
    path = config.notifications_dir / f"{stem}.json"
    cfg.atomic_write_text(path, notif.model_dump_json())
    return path


def _notif_disposition(
    notif: Notification, rules: list[notification_interrupt_policy.NotificationInterruptRule]
) -> tp.Literal["interrupt", "pool", "trash"]:
    """The notification's effective disposition: `interrupt`, `pool`, or `trash`. Core notifications are
    exempt from the user's rules — their disposition is control-flow, derived from the type
    (CORE_POOL_TYPES), and is never trashed; everything else goes through the ruleset (first match wins,
    else the producer's own interrupt default)."""
    if notif.source == CORE_SOURCE:
        return "pool" if notif.type in CORE_POOL_TYPES else "interrupt"
    return notification_interrupt_policy.notif_disposition(notif, rules)


async def load_notifications(*, config: cfg.VestaConfig) -> list[Notification]:
    file_contents = _load_notification_files(config.notifications_dir)

    notifications = []
    for file, content in file_contents:
        try:
            data = json.loads(content)
            notif = Notification(**data)
            notif.file_path = str(file)
            notifications.append(notif)
        except (json.JSONDecodeError, pydantic.ValidationError, KeyError, TypeError) as e:
            logger.error(f"Failed to parse notification {file.name}: {e}")
            file.unlink(missing_ok=True)

    return notifications


def _trash_paths(file_paths: list[str], trash_dir: pl.Path) -> None:
    """Move each notification file into the trash dir, replacing any same-named entry. Trashing keeps the
    file recoverable/auditable instead of deleting it; a parked file is never re-scanned (the loader
    globs non-recursively and the watcher ignores subdirs)."""
    if not file_paths:
        return
    trash_dir.mkdir(parents=True, exist_ok=True)
    for path_str in file_paths:
        source = pl.Path(path_str)
        if source.exists():
            source.replace(trash_dir / source.name)


async def trash_notification_files(notifications: list[Notification], *, trash_dir: pl.Path) -> None:
    _trash_paths([n.file_path for n in notifications if n.file_path], trash_dir)


_REPLY_SKILLS = frozenset({"app-chat", "whatsapp", "telegram"})


def _format_one(notif: Notification) -> str:
    """Embed hints inside the <channel> element so the model sees them as one unit.

    A reply hint points the model at the originating channel's reply skill instead of copying its CLI
    syntax. A group-chat message (a `chat_name` attribute is present) also gets a note that it may not
    be addressed to the agent, so the model decides whether to engage rather than always replying."""
    body = notif.format_for_display()
    if notif.type != "message" or notif.source not in _REPLY_SKILLS:
        return body
    extras = notif.model_extra or {}
    hints = []
    if "chat_name" in extras and extras["chat_name"]:
        hints.append("[This message is from a group chat and may not be for you; decide whether to chip in or stay out]")
    hints.append(f"[Reply using the `{notif.source}` skill]")
    hint = "\n" + "\n".join(hints)
    return body.replace("</channel>", f"{hint}\n</channel>")


def format_notification_batch(notifications: list[Notification], *, suffix: str = "") -> str:
    """Join the batch as newline-separated <channel> elements, matching how Claude Code delivers
    several native channel events together on one turn. No wrapper element: each <channel> is
    self-contained."""
    suffix_str = f"\n\n{suffix}" if suffix else ""
    inner = "\n".join(_format_one(n) for n in notifications)
    return f"{inner}{suffix_str}"


async def process_batch(
    notifications: list[Notification],
    *,
    queue: asyncio.Queue[vm.QueuedTurn],
    state: vm.State,
    config: cfg.VestaConfig,
) -> None:
    """Render a batch as one prompt and queue it. Internal (`source=core`) notifications skip the external-message suffix; mixed batches render in two sections, system first.

    Preempt delivery is owned by the processor's queue-watcher (_run_messages_with_interrupts):
    an item landing mid-turn is pre-sent there as a priority:"now" message. File paths are
    carried in the queue item and deleted only after the message is processed, so that a
    mid-compaction restart can recover unprocessed notifications from disk."""
    if not notifications:
        return

    # Interrupt mode preempts from here, at batch time (the queue-watcher's escalation covers
    # an interrupt that misses into an inter-turn gap). Don't SDK-abort a non-interruptible
    # boot turn: the batch is still queued below and the queue-watcher defers it.
    if config.preempt_mode == "interrupt" and state.client and not state.noninterruptible_turn_active:
        await attempt_interrupt(state, config=config, reason="Notification interrupt")

    system = [n for n in notifications if n.source == CORE_SOURCE]
    external = [n for n in notifications if n.source != CORE_SOURCE]

    async def queue_section(group: list[Notification], *, suffix: str) -> None:
        text = format_notification_batch(group, suffix=suffix)
        paths = [n.file_path for n in group if n.file_path]
        await queue.put(vm.QueuedTurn(text, False, paths))

    if system:
        await queue_section(system, suffix="")
    if external:
        await queue_section(external, suffix=load_prompt("notification_suffix", config) or "")


def greeting_turn(*, config: cfg.VestaConfig, state: vm.State, reason: str) -> str | None:
    """The boot greeting as a prompt body (or None to skip): first start runs the setup prompt,
    a restart builds the wake-up context (reason + restart prompt + any pending dreamer summary).

    Delivered as a boot turn rather than a notification — it is the agent's own startup context, not
    an external event, so it never enters the interrupt-rules/pool/triage machinery."""
    # Consume the one-shot boot message up front, before any early return, so it is delivered on the
    # boot it was set for and never strands to a later, unrelated restart (e.g. an unauthenticated
    # boot that returns None below). If this boot has no greeting to attach it to, it is discarded.
    boot_msg = state.persisted.pending_boot_message
    if boot_msg is not None:
        state.persisted.pending_boot_message = None
        state_store.save_state(state.persisted, config)

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

    extras = [boot_msg] if boot_msg is not None else []
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
    config: cfg.VestaConfig,
) -> None:
    """Run a turn and any follow-ups. The queue-watcher owns preempt delivery: an item arriving
    mid-turn is pre-sent via send_preempt and the running turn ends CLI-side on its own — this
    loop never aborts anything. preempt_mode="interrupt" only: a mid-turn item interrupts
    the current turn (deferred during compaction, never for a non-interruptible boot turn)."""

    async def run_one(text: str, *, user: bool, pre_sent: bool) -> None:
        try:
            if user:
                logger.user(text)
                state.event_bus.emit({"type": "user", "text": text})
            else:
                preview = text[:1000] + "..." if len(text) > 1000 else text
                logger.system(preview.replace("\n", " "))
            state.event_bus.set_state("thinking")
            await process_message(text, state=state, config=config, is_user=user, pre_sent=pre_sent)
        except asyncio.CancelledError:
            if state.shutdown_event.is_set() or state.graceful_shutdown.is_set():
                raise
            logger.error("Message processing cancelled unexpectedly, triggering restart")
            state.event_bus.emit({"type": "error", "text": "processing cancelled"})
            state.persisted.last_restart_reason = "error: a turn was cancelled unexpectedly"
            # Sync save on purpose: no awaits inside a cancellation handler (a second cancel would lose the write).
            state_store.save_state(state.persisted, config)
            state.graceful_shutdown.set()
            raise
        except (*SDK_ERRORS, ValueError, TimeoutError, QueryNotDelivered) as e:
            # QueryNotDelivered means the CLI never received the prompt (send timeout or a dead
            # transport): the outer loop must keep the notification file instead of clearing it,
            # mirroring the auth-loss branch, since the resumed session never saw the message.
            if isinstance(e, QueryNotDelivered):
                state.query_not_delivered = True
            error_msg = "Response timed out" if isinstance(e, TimeoutError) else (str(e) or type(e).__name__)
            exit_code, stderr_tail = format_crash_detail(e, state.stderr_buffer, fallback="")
            detail = f"Error processing message: {error_msg} | exit_code={exit_code}"
            if stderr_tail:
                detail += f"\nRecent stderr:\n{stderr_tail}"
            logger.error(f"{detail}, triggering restart")
            state.event_bus.emit({"type": "error", "text": error_msg})
            state.persisted.last_restart_reason = f"error: {error_msg}"
            await state_store.save_state_async(state.persisted, config)
            state.graceful_shutdown.set()
        finally:
            state.event_bus.set_state("idle")

    pending: list[vm.QueuedTurn] = [first]
    process_task: asyncio.Task[None] | None = None

    try:
        while pending:
            if state.graceful_shutdown.is_set():
                for remaining in pending:
                    await queue.put(remaining)
                break

            # Pre-sent items already jumped the CLI's prompt queue (priority:"now"), so they
            # must jump ours too: taking them first keeps Vesta's turn pairing aligned with
            # the order the CLI actually runs turns.
            index = next((i for i, item in enumerate(pending) if item.pre_sent), 0)
            current = pending.pop(index)
            # Defer (don't drive claude, don't delete the file) while unauthenticated: a dead token
            # just burns the CLI's full retry budget per message. Keeping the notification file on
            # disk means it re-runs after the user re-authenticates — which restarts the agent, so
            # monitor_loop re-reads the dir and re-queues it. (Migrations regenerate on boot anyway.)
            if is_unauthenticated(state.provider_status):
                logger.client("Provider not authenticated; deferring message until re-auth")
                continue
            state.interrupt_event = asyncio.Event()
            state.noninterruptible_turn_active = not current.interruptible
            state.in_flight_notification_paths = current.file_paths
            state.query_not_delivered = False
            process_task = asyncio.create_task(run_one(current.text, user=current.is_user, pre_sent=current.pre_sent))

            while not process_task.done():
                queue_task: asyncio.Task[vm.QueuedTurn] = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({process_task, queue_task}, return_when=asyncio.FIRST_COMPLETED)

                if queue_task in done:
                    arrived = queue_task.result()
                    # The single owner of preempt delivery: an item landing while a turn runs is
                    # pre-sent as a priority:"now" message, ending the turn at its next step
                    # boundary with background subagents intact (issue #982). send_preempt
                    # self-gates (idle, boot turn, compaction, auth), so a miss just queues plain.
                    if (
                        config.preempt_mode == "message"
                        and not arrived.pre_sent
                        and await send_preempt(arrived.text, state=state, config=config)
                    ):
                        arrived = arrived._replace(pre_sent=True)
                    pending.append(arrived)
                    if config.preempt_mode == "message":
                        continue
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
                    await cancel_task(queue_task)

            await process_task
            state.noninterruptible_turn_active = False
            # Keep the file if the turn flipped auth to not_authenticated (converse detects a
            # terminal 401/402 mid-turn) or the query never reached the CLI (state.query_not_delivered):
            # like a deferred message above, either way it must re-run, on re-auth or on the next
            # restart. Operate on in_flight_notification_paths, not current.file_paths: an intentional
            # restart mid-turn already cleared and emptied it, so this stays a no-op instead of re-emitting.
            authenticated = state.provider_status is None or state.provider_status.state == ProviderAuthState.AUTHENTICATED
            if authenticated and not state.query_not_delivered:
                clear_notifications(state, state.in_flight_notification_paths)
            state.in_flight_notification_paths = []
            state.query_not_delivered = False
            process_task = None
            state.interrupt_event = None
    except asyncio.CancelledError:
        if process_task:
            await cancel_task(process_task)
        raise
    finally:
        state.noninterruptible_turn_active = False


# The one core-owned follow-up string: a fact only core can state (it ran /compact, so the prior
# conversation is now the summary at the top of context). Prepended to a follow-up ONLY when the
# compaction actually succeeded, so we never falsely claim a summary is above. "above" holds in
# both channels (live notification on the compacted session; boot greeting resuming it).
COMPACTION_ORIENTATION = "[Your context was just compacted; the summary is above.]"


def _followup_turn(followup: str, *, compacted_ok: bool) -> str:
    # Only claim the compaction happened if it did; otherwise deliver the caller's intent bare.
    return f"{COMPACTION_ORIENTATION}\n\n{followup}" if compacted_ok else followup


async def drain_compaction_request(*, state: vm.State, config: cfg.VestaConfig) -> None:
    """Drain a deferred compaction. Compact, then route the optional follow-up to the channel
    that survives a restart: a boot message when restarting (a live notification would race the
    SIGTERM), a live notification otherwise. Compaction failure is logged, not fatal: the
    follow-up is still delivered (without the false 'summary above' claim) and the restart still
    happens (resume works on the un-compacted session)."""
    pending = state.pending_compaction
    state.pending_compaction = None
    if state.client is None or pending is None:
        return
    logger.client(f"Compacting session (restart={pending.restart})")
    state.event_bus.set_state("thinking")
    state.compacting = True
    compacted_ok = True
    try:
        await compact_session(state=state, config=config, prompt=pending.prompt)
    except (*SDK_ERRORS, TimeoutError) as exc:
        compacted_ok = False
        logger.warning(f"compaction failed: {exc}")
    finally:
        state.compacting = False
        state.event_bus.set_state("idle")

    turn = _followup_turn(pending.followup, compacted_ok=compacted_ok) if pending.followup is not None else None
    deliver_live = not pending.restart
    if pending.restart:
        if turn is not None:
            # Persist before requesting the restart: vestad SIGTERMs us during request_restart(),
            # so there is no later moment to write it.
            state.persisted.pending_boot_message = turn
            await state_store.save_state_async(state.persisted, config)
        # vestad owns the restart and starts us back on the compacted session. If it is unreachable
        # we stay up on this session, so the boot channel is moot: clear it and fall back to the
        # live channel below instead of losing the follow-up.
        if not await vestad_client.request_restart():
            logger.warning("vestad unreachable for restart; continuing on the compacted session")
            if turn is not None:
                state.persisted.pending_boot_message = None
                await state_store.save_state_async(state.persisted, config)
            deliver_live = True
    if deliver_live and turn is not None:
        drop_core_notification(type_=TYPE_COMPACTION_FOLLOWUP, body=turn, config=config)


async def message_processor(queue: asyncio.Queue[vm.QueuedTurn], *, state: vm.State, config: cfg.VestaConfig) -> None:
    # An agent with no authenticated provider can't drive the model. It still boots and stays reachable
    # so vestad can deliver credentials over the API, but there is nothing to process here until sign-in
    # restarts the process with a provider applied — so idle instead of building an SDK client (which
    # requires a provider). Messages are deferred upstream while unauthenticated, so the queue stays empty.
    if state.provider_status is None or state.provider_status.state != ProviderAuthState.AUTHENTICATED:
        logger.client("No authenticated provider; idling until sign-in")
        await state.shutdown_event.wait()
        return
    logger.client("Creating new client session...")
    if isinstance(config.provider, cfg.OpenRouterConfig):
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
    async with client_session(state=state, config=config):
        while not state.shutdown_event.is_set():
            try:
                turn = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue

            state.processor_busy = True
            try:
                await _run_messages_with_interrupts(turn, queue=queue, state=state, config=config)
                await drain_compaction_request(state=state, config=config)
            finally:
                state.processor_busy = False


# --- Proactive & dreamer ---


def check_proactive_task(*, config: cfg.VestaConfig) -> None:
    prompt = load_prompt("proactive_check", config)
    if not prompt:
        return
    logger.proactive(f"Running {config.proactive_check_interval}-minute check...")
    drop_core_notification(type_=TYPE_PROACTIVE_CHECK, body=prompt, config=config)


DREAMER_CATCHUP_HOURS = 6


def process_nightly_memory(*, state: vm.State, config: cfg.VestaConfig) -> None:
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


async def monitor_loop(queue: asyncio.Queue[vm.QueuedTurn], *, state: vm.State, config: cfg.VestaConfig) -> None:
    last_proactive = _now()
    # Init one hour back so the first dreamer check runs on the first tick after boot.
    last_dreamer_check = _now() - dt.timedelta(hours=1)
    pending_passive: list[Notification] = []
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
                if state.processor_busy or not queue.empty():
                    logger.debug("Proactive check skipped: agent is busy, retrying next tick")
                else:
                    last_proactive = now
                    check_proactive_task(config=config)

            if (now - last_dreamer_check).total_seconds() >= 3600:
                process_nightly_memory(state=state, config=config)
                last_dreamer_check = now

            # Prune paths that were processed and deleted; this is how we know a queued item
            # completed and its file is gone, preventing unbounded set growth.
            queued_paths = {p for p in queued_paths if pl.Path(p).exists()}

            notifications = await load_notifications(config=config)
            rules = await asyncio.to_thread(cfg.load_notification_rules)
            fresh = [n for n in notifications if not n.file_path or n.file_path not in queued_paths]
            decisions = [(n, _notif_disposition(n, rules)) for n in fresh]
            interrupt_notifs = [n for n, disposition in decisions if disposition == "interrupt"]
            new_passive = [n for n, disposition in decisions if disposition == "pool"]
            trashed = [n for n, disposition in decisions if disposition == "trash"]

            # Emit each genuinely-new notification to the bus exactly once, enriched with structured
            # facets + the effective disposition for the history view. load_notifications re-reads every
            # file each tick, so files kept on disk (e.g. deferred while unauthenticated) must not
            # re-emit — that was the notification storm.
            for notif, disposition in decisions:
                state.event_bus.emit(
                    {
                        "type": "notification",
                        "source": notif.source,
                        "summary": notif.format_for_display(),
                        "notif_type": notif.type,
                        "sender": notification_interrupt_policy.notif_sender(notif) or "",
                        "fields": notification_interrupt_policy.notif_facet_fields(notif),
                        "decided": disposition,
                        "notif_id": pl.Path(notif.file_path).stem if notif.file_path else "",
                    }
                )

            # Trashed notifications are recorded in history above but never reach the agent: move the
            # files out of the active dir (recoverable, and so they never re-emit) and create no turn.
            # They are resolved the moment they arrive, so clear each one's pending marker right away —
            # the arrival emit carried a notif_id, and without a matching notification_cleared the
            # history view would show a trashed notification pending forever.
            if trashed:
                await trash_notification_files(trashed, trash_dir=config.notif_trash_dir)
                for notif in trashed:
                    if notif.file_path:
                        state.event_bus.emit({"type": "notification_cleared", "notif_id": pl.Path(notif.file_path).stem})

            queued_paths.update(n.file_path for n, disposition in decisions if disposition != "trash" and n.file_path)
            pending_passive.extend(new_passive)

            if interrupt_notifs:
                await process_batch(interrupt_notifs, queue=queue, state=state, config=config)

            # Track how long the agent has been continuously idle; micro-gaps shorter than the
            # grace never qualify, so a brief breather between turns doesn't flush the pool.
            if state.event_bus.state == "idle":
                if idle_since is None:
                    idle_since = now
            else:
                idle_since = None

            if pending_passive and idle_since is not None and (now - idle_since).total_seconds() >= config.notif_pool_idle_grace_seconds:
                await process_batch(pending_passive, queue=queue, state=state, config=config)
                pending_passive = []
    finally:
        await cancel_task(watcher_task)
