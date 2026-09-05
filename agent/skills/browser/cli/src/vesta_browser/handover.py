"""Handing one session to the user: a headed browser on a private display, reachable at one keyed URL.

The whole flow lives here because every piece of it is one decision: the display stack, the headed
engine, the vestad service and its key, the lifetime, and the teardown that must run whichever of
them failed. The session is marked `handed_over` for the duration, so no exec can drive the browser
the user is holding, and the teardown always ends with the session `stopped` and ready to run
headless again.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import os
import shutil
import typing as tp
import uuid

from . import display, gateway
from . import protocol as p
from . import sessions as sessions_mod
from .daemon_state import State
from .handover_state import Handover, StopReason, payload
from .procs import KILL_GRACE_SECS, kill_group
from .runtime_paths import Paths
from .runtimes import EngineRuntime, HeadedDisplay
from .session_control import ENGINES, _stop_session

logger = logging.getLogger(__name__)
SERVICE = "browser"
MINUTE_SECS = 60.0
LIFETIME_DEFAULT_MINUTES = 30
LIFETIME_MIN_MINUTES = 1
LIFETIME_MAX_MINUTES = 240
NAVIGATE_TIMEOUT_SECS = 60


def _in_use(message: str) -> p.BrowserError:
    return p.BrowserError(p.error("handover_in_use", "handover", message, retryable=True, suggested_action="run: browser handover stop"))


def _failed(message: str) -> p.BrowserError:
    return p.BrowserError(p.error("handover_failed", "handover", message, retryable=True, suggested_action="run: browser doctor"))


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


async def _start_display(paths: Paths, web_port: int) -> display.DisplayStack:
    """The four processes the page needs, torn back down together if any of them never comes up."""
    started: list[asyncio.subprocess.Process] = []
    try:
        name, xvfb = await display.claim_display(paths)
        started.append(xvfb)
        webroot = await asyncio.to_thread(display.build_webroot, paths)
        openbox = await display.start_openbox(paths, name)
        started.append(openbox)
        vnc_port = await asyncio.to_thread(display.free_port, display.VNC_PORT_FIRST)
        x11vnc = await display.start_x11vnc(name, vnc_port)
        started.append(x11vnc)
        websockify = await display.start_websockify(webroot, web_port, vnc_port, paths.log)
    except Exception:
        await asyncio.gather(*[kill_group(process, KILL_GRACE_SECS) for process in reversed(started)], return_exceptions=True)
        raise
    return display.DisplayStack(name, xvfb, openbox, x11vnc, websockify, vnc_port, web_port, webroot)


def _healthy(paths: Paths, handover: Handover) -> bool:
    """The four facts a live handover rests on: our display, the VNC port, the web port, the browser."""
    stack = handover.stack
    runtime = handover.session.runtime
    if stack is None or runtime is None:
        return False
    number = int(stack.display.lstrip(":").split(".")[0])
    return (
        display.own_display_serving(paths, number)
        and display.port_serving(stack.vnc_port)
        and display.port_serving(stack.web_port)
        and runtime.process.returncode is None
    )


async def _navigate(paths: Paths, session: sessions_mod.Session, runtime: EngineRuntime, url: str) -> list[str]:
    outcome = await ENGINES[session.engine].exec_code(runtime, session, paths, f"new_tab({url!r})", NAVIGATE_TIMEOUT_SECS)
    return [] if outcome.exit_code == 0 else ["navigation_failed"]


async def _bring_up(state: State, handover: Handover, *, public_url: str, agent: str, url: str | None, minutes: int) -> list[str]:
    """Everything between a marked session and a live handover, in the one order that works."""
    paths = state.paths
    session = handover.session
    web_port = await gateway.register_service(SERVICE)
    handover.stack = await _start_display(paths, web_port)
    headed = HeadedDisplay(handover.stack.display, display.SCREEN_W, display.SCREEN_H)
    runtime = await ENGINES[session.engine].start(session, paths, headed=headed)
    session.runtime = runtime
    warnings = await _navigate(paths, session, runtime, url) if url is not None else []
    secret = await gateway.mint_key(SERVICE, handover.key_label, int(minutes * MINUTE_SECS))
    handover.key_id = await gateway.find_key_id(SERVICE, handover.key_label)
    handover.user_url = f"{public_url.rstrip('/')}/agents/{agent}/{SERVICE}/k/{secret}/handover.html"
    if not await asyncio.to_thread(_healthy, paths, handover):
        raise _failed("the display stack came up but is not serving")
    handover.state = "live"
    handover.task = _own(state, _expire(state, minutes))
    return warnings


async def start(state: State, *, session_name: str, mode: p.Mode | None, url: str | None, minutes: int) -> tuple[Handover, list[str]]:
    """Hands `session_name` to the user. Any failure past the mark tears the whole attempt down."""
    live = state.handover
    if live is not None and live.state in ("starting", "live", "stopping"):
        raise _in_use(f"a handover is already {live.state} on session {live.session.name!r}")
    public_url = _env("VESTAD_PUBLIC_URL")
    agent = _env("AGENT_NAME")
    ready = display.readiness(state.paths)
    if ready["ready"] is not True:
        raise _failed(f"the handover display needs {ready['missing']}. Install it: {display.HANDOVER_APT_LINE}")
    session = sessions_mod.resolve_session(state.table, session_name, mode)
    if session.state in ("busy", "starting"):
        raise p.BrowserError(p.invalid(f"session {session_name!r} is {session.state}; retry once the current request finishes"))
    await _stop_session(session)
    sessions_mod.mark(session, "handed_over")
    handover_id = uuid.uuid4().hex[:8]
    handover = Handover(
        id=handover_id,
        session=session,
        key_label=f"browser-handover-{handover_id}",
        expires_at=_expiry_iso(minutes),
        state="starting",
    )
    state.handover = handover
    try:
        warnings = await _bring_up(state, handover, public_url=public_url, agent=agent, url=url, minutes=minutes)
    except Exception as exc:
        await stop(state, reason="failed")
        raise _failed(str(exc) or type(exc).__name__) from exc
    return handover, warnings


async def _expire(state: State, minutes: int) -> None:
    await asyncio.sleep(minutes * MINUTE_SECS)
    await stop(state, reason="expired")


async def _stop_failed(state: State) -> None:
    await stop(state, reason="failed")


async def _guarded(step: tp.Awaitable[object], what: str) -> bool:
    try:
        await step
    except Exception:
        logger.exception("handover teardown could not %s", what)
        return False
    return True


async def _cancel_expiry(handover: Handover) -> None:
    task = handover.task
    handover.task = None
    if task is None or task is asyncio.current_task():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _release_key(handover: Handover, timeout: float) -> None:
    key_id = handover.key_id if handover.key_id is not None else await gateway.find_key_id(SERVICE, handover.key_label, timeout=timeout)
    handover.key_id = None
    if key_id is not None:
        await gateway.revoke_key(SERVICE, key_id, timeout=timeout)


async def _tear_display(paths: Paths, handover: Handover) -> None:
    stack = handover.stack
    handover.stack = None
    if stack is not None:
        await display.stop_stack(paths, stack)


async def stop(state: State, *, reason: StopReason, gateway_timeout: float = gateway.GATEWAY_TIMEOUT_SECS) -> list[str]:
    """Every teardown step attempted, whatever the one before it did. Idempotent, and safe to call
    on a handover that never finished starting: each step owns whether it has anything to undo."""
    handover = state.handover
    if handover is None or handover.state in ("inactive", "stopping"):
        return []
    handover.state = "stopping"
    done = [
        await _guarded(_cancel_expiry(handover), "cancel the expiry timer"),
        await _guarded(_release_key(handover, gateway_timeout), "revoke the handover key"),
        await _guarded(gateway.deregister_service(SERVICE, timeout=gateway_timeout), "deregister the service"),
        await _guarded(_stop_session(handover.session, force=True), "stop the headed browser"),
        await _guarded(_tear_display(state.paths, handover), "stop the display stack"),
        await _guarded(asyncio.to_thread(shutil.rmtree, state.paths.handover_web, ignore_errors=True), "remove the web root"),
    ]
    handover.state = "inactive" if reason == "stopped" else reason
    sessions_mod.mark(handover.session, "stopped")
    return [] if all(done) else ["cleanup_incomplete"]


async def status(state: State) -> dict[str, p.JsonValue]:
    """The current payload, with a live handover's health re-read: a broken one reports and stops."""
    handover = state.handover
    if handover is not None and handover.state == "live" and not await asyncio.to_thread(_healthy, state.paths, handover):
        handover.state = "failed"
        _own(state, _stop_failed(state))
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
    warnings = await stop(state, reason="stopped")
    session = sessions_mod.info(live.session) if live is not None else None
    return p.result(request_id=request_id, op="handover_stop", ok=True, session=session, data=payload(state.handover), warnings=warnings)
