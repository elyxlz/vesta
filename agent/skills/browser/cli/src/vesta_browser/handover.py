"""Handing one session to the user: its own live display, reachable at one keyed URL.

The handover owns the stream alone, an x11vnc and a websockify on the display the session already
holds; the session owns the browser and that display. The rest of the flow lives here because every
piece of it is one decision: the vestad service and its key, the lifetime, and the teardown that
must run whichever of them failed. The session is marked `handed_over` for the duration, so no exec
can drive the browser the user is holding, and the teardown gives it back on the same display, with
everything the user did still in front of it.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import os
import shutil
import time
import typing as tp
import uuid

from . import display, gateway
from . import protocol as p
from . import sessions as sessions_mod
from .daemon_state import State
from .handover_state import Handover, StopReason, payload
from .procs import KILL_GRACE_SECS, kill_group
from .runtime_paths import Paths
from .runtimes import EngineRuntime
from .session_control import ENGINES, ensure_running, stop_session

logger = logging.getLogger(__name__)
SERVICE = "browser"
MINUTE_SECS = 60.0
LIFETIME_DEFAULT_MINUTES = 30
LIFETIME_MIN_MINUTES = 1
LIFETIME_MAX_MINUTES = 240
NAVIGATE_TIMEOUT_SECS = 30
# One deadline for the whole start, the engine's own launch included: what the client waits
# behind, under the CLI's own RPC timeout. Every step inside it has its own bound too, and a start
# still running at this point is one the user is no longer waiting for.
HANDOVER_START_BUDGET_SECS = 100.0
# A rollback runs while a SIGTERM may already be in flight, so it never waits on vestad as long as
# a foreground call does: the daemon must be gone before `browser daemon stop` SIGKILLs it.
ROLLBACK_GATEWAY_TIMEOUT_SECS = 5.0
# A shutdown slice this short still lets a step start; it exists so a spent budget never passes
# `asyncio.wait_for` a zero or negative timeout, which would cancel the step before it runs.
MIN_SHUTDOWN_SLICE_SECS = 0.05
SETTLE_POLL_SECS = 0.02


def _in_use(message: str) -> p.BrowserError:
    return p.BrowserError(p.error("handover_in_use", "handover", message, retryable=True, suggested_action="run: browser handover stop"))


def _failed(message: str) -> p.BrowserError:
    return p.BrowserError(p.error("handover_failed", "handover", message, retryable=True, suggested_action="run: browser doctor"))


def _too_slow() -> p.BrowserError:
    return _failed(f"the handover was still coming up after {HANDOVER_START_BUDGET_SECS}s")


def _env(name: str) -> str:
    if name not in os.environ or not os.environ[name]:
        raise _failed(f"{name} is not set in the daemon's environment")
    return os.environ[name]


def _expiry_iso(minutes: int) -> str:
    when = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=minutes)
    return when.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _own(state: State, coro: tp.Coroutine[None, None, None]) -> asyncio.Task[None]:
    """Every task this module spawns is held by the daemon, so shutdown cancels and awaits it."""
    task = asyncio.create_task(coro)
    state.tasks.add(task)
    task.add_done_callback(state.tasks.discard)
    return task


async def _start_stream(paths: Paths, display_name: str, web_port: int) -> display.StreamStack:
    """The stream on the display `display_name` names, torn back down if either process fails."""
    started: list[asyncio.subprocess.Process] = []
    try:
        webroot = await asyncio.to_thread(display.build_webroot, paths)
        vnc_port = await asyncio.to_thread(display.free_port, display.VNC_PORT_FIRST)
        x11vnc = await display.start_x11vnc(display_name, vnc_port)
        started.append(x11vnc)
        websockify = await display.start_websockify(webroot, web_port, vnc_port, paths.log)
    except BaseException:
        await asyncio.gather(*[kill_group(process, KILL_GRACE_SECS) for process in reversed(started)], return_exceptions=True)
        raise
    return display.StreamStack(x11vnc, websockify, vnc_port, web_port, webroot)


def _healthy(paths: Paths, handover: Handover) -> bool:
    """The four facts a live handover rests on: the display, the VNC port, the web port, the browser."""
    session = handover.session
    stack = handover.stack
    if session.display is None or session.runtime is None or stack is None:
        return False
    return (
        display.own_display_serving(paths, display.display_number(session.display.display))
        and display.port_serving(stack.vnc_port)
        and display.port_serving(stack.web_port)
        and session.runtime.process.returncode is None
    )


async def _navigate(paths: Paths, session: sessions_mod.Session, runtime: EngineRuntime, url: str) -> list[str]:
    # Both engines open a new tab behind the visible one; activate= is what puts it in front of the user.
    code = f"switch_tab(new_tab({url!r}), activate=True)"
    outcome = await ENGINES[session.engine].exec_code(runtime, session, paths, code, NAVIGATE_TIMEOUT_SECS)
    return [] if outcome.exit_code == 0 else ["navigation_failed"]


async def _bring_up(
    state: State, handover: Handover, *, public_url: str, agent: str, url: str | None, minutes: int, warnings: list[str]
) -> None:
    """Everything between a marked session and a live handover, in the one order that works.

    Warnings land in the list the caller owns, because this runs as a task: a cancelled bring-up has
    no return value to carry them home.
    """
    paths = state.paths
    session = handover.session
    assert session.display is not None and session.runtime is not None
    web_port = await gateway.register_service(SERVICE)
    handover.stack = await _start_stream(paths, session.display.display, web_port)
    if url is not None:
        warnings.extend(await _navigate(paths, session, session.runtime, url))
    secret = await gateway.mint_key(SERVICE, handover.key_label, int(minutes * MINUTE_SECS))
    handover.expires_at = _expiry_iso(minutes)
    handover.key_id = await gateway.find_key_id(SERVICE, handover.key_label)
    handover.user_url = f"{public_url.rstrip('/')}/agents/{agent}/{SERVICE}/k/{secret}/handover.html"
    if not await asyncio.to_thread(_healthy, paths, handover):
        raise _failed("the display stack came up but is not serving")
    handover.state = "live"
    handover.task = _own(state, _expire(state, handover, minutes))


async def start(state: State, *, session_name: str, mode: p.Mode | None, url: str | None, minutes: int) -> tuple[Handover, list[str]]:
    """Hands `session_name` to the user. Any failure past the mark tears the whole attempt down."""
    live = state.handover
    if live is not None and live.state in ("starting", "live", "stopping"):
        raise _in_use(f"a handover is already {live.state} on session {live.session.name!r}")
    public_url = _env("VESTAD_PUBLIC_URL")
    agent = _env("AGENT_NAME")
    missing = [*display.missing_display_binaries(state.paths), *display.missing_stream_binaries(state.paths)]
    if missing:
        raise _failed(f"the handover display needs {', '.join(missing)}. Install it: {display.DISPLAY_APT_LINE}")
    session = sessions_mod.resolve_session(state.table, session_name, mode)
    if session.state in ("busy", "starting"):
        raise p.BrowserError(p.invalid(f"session {session_name!r} is {session.state}; retry once the current request finishes"))
    deadline = time.monotonic() + HANDOVER_START_BUDGET_SECS
    handover_id = uuid.uuid4().hex[:8]
    handover = Handover(id=handover_id, session=session, key_label=f"browser-handover-{handover_id}", state="starting")
    # Claimed with no await between the check above and this line, so a second start arriving while
    # this one waits on the engine is refused rather than replacing it.
    state.handover = handover
    # The browser comes up before the session is marked or anything is registered, because an engine
    # that cannot start is the session's own failure to report, with no handover to roll back.
    try:
        warnings = await asyncio.wait_for(ensure_running(state, session), deadline - time.monotonic())
    except TimeoutError as exc:
        state.handover = None
        raise _too_slow() from exc
    except BaseException:
        state.handover = None
        raise
    sessions_mod.mark(session, "handed_over")
    # The bring-up runs as a task the daemon owns, because it holds the stream for as long as it
    # runs: a shutdown must be able to cancel it and take the stream back.
    bring_up = _own(state, _bring_up(state, handover, public_url=public_url, agent=agent, url=url, minutes=minutes, warnings=warnings))
    handover.task = bring_up
    try:
        await asyncio.wait_for(asyncio.shield(bring_up), deadline - time.monotonic())
    except TimeoutError as exc:
        await stop(state, handover, reason="failed", gateway_timeout=ROLLBACK_GATEWAY_TIMEOUT_SECS)
        raise _too_slow() from exc
    except BaseException as exc:
        # The shield keeps an outer cancellation off the bring-up, so which of the two was cancelled
        # is what tells them apart: this caller going away is not a handover failure to report. Read
        # before `stop` runs, since `stop` itself cancels the bring-up as part of its teardown.
        bring_up_was_cancelled = bring_up.cancelled()
        await stop(state, handover, reason="failed", gateway_timeout=ROLLBACK_GATEWAY_TIMEOUT_SECS)
        if isinstance(exc, asyncio.CancelledError) and not bring_up_was_cancelled:
            raise
        raise _failed(str(exc) or type(exc).__name__) from exc
    return handover, warnings


async def _expire(state: State, handover: Handover, minutes: int) -> None:
    await asyncio.sleep(minutes * MINUTE_SECS)
    await stop(state, handover, reason="expired")


async def _stop_failed(state: State, handover: Handover) -> None:
    await stop(state, handover, reason="failed")


async def _guarded(step: tp.Awaitable[bool | None], what: str) -> bool:
    try:
        await step
    except Exception:
        logger.exception("handover teardown could not %s", what)
        return False
    return True


async def _cancel_task(handover: Handover) -> None:
    """Drops whatever the handover currently owns: the bring-up while starting, the timer once live."""
    task, handover.task = handover.task, None
    if task is None or task.done() or task is asyncio.current_task():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _release_key(handover: Handover, timeout: float) -> None:
    """The URL goes first, before anything that can fail: a key on its way out must stop printing."""
    key_id, handover.key_id = handover.key_id, None
    handover.user_url = ""
    if key_id is None:
        key_id = await gateway.find_key_id(SERVICE, handover.key_label, timeout=timeout)
    if key_id is not None:
        await gateway.revoke_key(SERVICE, key_id, timeout=timeout)


async def _tear_stream(handover: Handover) -> None:
    stack, handover.stack = handover.stack, None
    if stack is not None:
        await display.stop_stack(stack)


async def _teardown(state: State, handover: Handover, reason: StopReason, gateway_timeout: float) -> list[str]:
    """Every step attempted, whatever the one before it did, so a failed revoke never skips the
    deregister. Each step owns whether it has anything to undo, so a half-started handover is fine.

    The session gets its browser back on the display it has held all along, `ready` for the next
    exec. A runtime that died under the user is reaped with that display instead, and the session is
    queued for a restart, so the next exec starts a fresh browser and says it did.
    """
    session = handover.session
    done = [
        await _guarded(_cancel_task(handover), "drop the task it owns"),
        await _guarded(_release_key(handover, gateway_timeout), "revoke the handover key"),
        await _guarded(gateway.deregister_service(SERVICE, timeout=gateway_timeout), "deregister the service"),
        await _guarded(_tear_stream(handover), "stop the stream"),
        await _guarded(asyncio.to_thread(shutil.rmtree, state.paths.handover_web, ignore_errors=True), "remove the web root"),
    ]
    handover.state = "inactive" if reason == "stopped" else reason
    if session.runtime is not None and session.runtime.process.returncode is None:
        sessions_mod.mark(session, "ready")
    else:
        done.append(await _guarded(stop_session(state.paths, session, force=True), "reap the browser that died"))
        state.restart_pending.add(session.name)
    sessions_mod.touch(state.table, session)
    return [] if all(done) else ["cleanup_incomplete"]


async def stop(state: State, handover: Handover, *, reason: StopReason, gateway_timeout: float = gateway.GATEWAY_TIMEOUT_SECS) -> list[str]:
    """Gives `handover` back, once. A caller holding a handover the daemon has already replaced or
    torn down gets a no-op, so a timer firing late can never touch the handover that came after it.

    A handover still claiming its browser holds no task and no stream, and the engine is launching
    onto the session's display: a stop arriving there is refused rather than served, because the
    teardown would take that display away mid-launch and leave the session marked for the handover
    that never came up.
    """
    if state.handover is not handover or handover.state in ("inactive", "stopping"):
        return []
    if handover.state == "starting" and handover.task is None:
        raise _in_use("the handover is still starting its browser; retry in a moment")
    handover.state = "stopping"
    return await _teardown(state, handover, reason, gateway_timeout)


def _slice(deadline: float) -> float:
    return max(deadline - time.monotonic(), MIN_SHUTDOWN_SLICE_SECS)


async def _settle(handover: Handover, deadline: float) -> None:
    """Waits out a teardown another task already started, so the shutdown that follows cannot cancel
    that task halfway through it."""
    while time.monotonic() < deadline:
        if handover.state != "stopping":
            return
        await asyncio.sleep(SETTLE_POLL_SECS)


async def shutdown(state: State, *, budget: float, gateway_timeout: float) -> None:
    """The daemon taking a handover back on its way out, inside `budget`.

    The state is claimed before the bring-up is cancelled, so the `start` waiting on that task rolls
    nothing back itself and this is the one teardown. Whatever the budget cuts short, the stream is
    still killed here. The browser and the display under it are the session's own, left whole for
    the session teardown that follows, which is the one budget with a SIGKILL behind it.
    """
    handover = state.handover
    if handover is None or handover.state == "inactive":
        return
    deadline = time.monotonic() + budget
    if handover.state in ("starting", "live"):
        handover.state = "stopping"
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(_cancel_task(handover), _slice(deadline))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(_teardown(state, handover, "stopped", gateway_timeout), _slice(deadline))
    else:
        await _settle(handover, deadline)
    await _guarded(_tear_stream(handover), "stop the stream")


async def status(state: State) -> dict[str, p.JsonValue]:
    """The current payload, with a live handover's health re-read: a broken one reports and stops."""
    handover = state.handover
    if handover is not None and handover.state == "live" and not await asyncio.to_thread(_healthy, state.paths, handover):
        handover.state = "failed"
        _own(state, _stop_failed(state, handover))
    return payload(handover)


def _read_start(request: dict[str, p.JsonValue]) -> tuple[str, p.Mode | None, str | None, int]:
    session = request["session"] if "session" in request and request["session"] is not None else p.DEFAULT_SESSION
    if not isinstance(session, str):
        raise p.BrowserError(p.invalid("session must be a string"))
    mode = request["mode"] if "mode" in request else None
    if mode not in (None, "standard", "stealth"):
        raise p.BrowserError(p.invalid("mode must be standard, stealth, or null"))
    url = request["url"] if "url" in request else None
    if url is not None and not isinstance(url, str):
        raise p.BrowserError(p.invalid("url must be a string"))
    minutes = request["minutes"] if "minutes" in request and request["minutes"] is not None else LIFETIME_DEFAULT_MINUTES
    if not isinstance(minutes, int) or isinstance(minutes, bool) or not LIFETIME_MIN_MINUTES <= minutes <= LIFETIME_MAX_MINUTES:
        raise p.BrowserError(p.invalid(f"minutes must be an integer between {LIFETIME_MIN_MINUTES} and {LIFETIME_MAX_MINUTES}"))
    return session, tp.cast(p.Mode | None, mode), url, minutes


async def op_handover_start(state: State, request_id: str, request: dict[str, p.JsonValue]) -> p.Result:
    session_name, mode, url, minutes = _read_start(request)
    handover, warnings = await start(state, session_name=session_name, mode=mode, url=url, minutes=minutes)
    return p.result(
        request_id=request_id,
        op="handover_start",
        ok=True,
        session=sessions_mod.info(handover.session),
        data=payload(handover),
        warnings=warnings,
    )


async def op_handover_status(state: State, request_id: str, _request: dict[str, p.JsonValue]) -> p.Result:
    live = state.handover
    session = sessions_mod.info(live.session) if live is not None else None
    return p.result(request_id=request_id, op="handover_status", ok=True, session=session, data=await status(state))


async def op_handover_stop(state: State, request_id: str, _request: dict[str, p.JsonValue]) -> p.Result:
    live = state.handover
    warnings = await stop(state, live, reason="stopped") if live is not None else []
    session = sessions_mod.info(live.session) if live is not None else None
    return p.result(request_id=request_id, op="handover_stop", ok=True, session=session, data=payload(state.handover), warnings=warnings)
