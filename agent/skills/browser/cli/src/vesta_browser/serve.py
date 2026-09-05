"""The browser daemon: one unix socket, one JSON line per request, one owner for every browser decision.

`browser daemon start` runs `browser serve` detached; nothing else launches this. Handlers return a
`protocol.Result`, and a `BrowserError` raised anywhere inside a handler becomes the failed result
for that request alone.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import pathlib as pl
import signal
import socket
import sys
import time
import typing as tp

from . import artifacts, doctor, gateway, handover
from . import protocol as p
from . import sessions as sessions_mod
from .daemon_state import State, routes
from .procs import KILL_GRACE_SECS, kill_group
from .runtime_paths import Paths, load_paths
from .runtimes import ExecOutcome
from .session_control import ENGINES, ensure_running, stop_session

logger = logging.getLogger(__name__)
IDLE_SWEEP_SECS = 60
IDLE_STOP_SECS = p.SESSION_IDLE_STOP_SECS
PRUNE_INTERVAL_SECS = 3600
# `browser daemon stop` SIGKILLs this process two thirds into its own 15s budget, so every teardown
# below shares one budget under that 10s point. A live handover's own steps stay inside
# HANDOVER_SHUTDOWN_SECS and end only the stream stack, since the display beneath it is a session's
# own and outlives any one handover of it. The sessions then get whatever SHUTDOWN_BUDGET_SECS has
# left of that spend (floored at MIN_SESSION_BUDGET_SECS) to stop their own engine and display, each
# escalating past that budget at its own KILL_GRACE_SECS. A hung chromium launch or camoufox's stop
# can still overrun its own finally.
SHUTDOWN_BUDGET_SECS = 6.0
HANDOVER_SHUTDOWN_SECS = 2.0
SHUTDOWN_GATEWAY_TIMEOUT_SECS = 0.6
MIN_SESSION_BUDGET_SECS = 1.0
STARTUP_DEREGISTER_TIMEOUT_SECS = 5.0


async def op_status(state: State, request_id: str, _request: dict[str, p.JsonValue]) -> p.Result:
    data: p.JsonValue = {"protocol_version": p.PROTOCOL_VERSION, "pid": os.getpid(), "socket": str(state.paths.socket)}
    return p.result(request_id=request_id, op="status", ok=True, data=data)


async def op_engines(state: State, request_id: str, _request: dict[str, p.JsonValue]) -> p.Result:
    return p.result(request_id=request_id, op="engines", ok=True, data=routes(state.paths))


def _validate_exec(request: dict[str, p.JsonValue]) -> tuple[str, p.Mode | None, int, str, list[str]]:
    """Returns (session, mode, timeout_s, code, warnings) or raises BrowserError(invalid_request)."""
    code = request["code"] if "code" in request else ""
    if not isinstance(code, str) or not code.strip():
        raise p.BrowserError(p.invalid("code is empty"))
    if len(code.encode()) > p.CODE_MAX_BYTES:
        raise p.BrowserError(p.invalid(f"code exceeds {p.CODE_MAX_BYTES} bytes"))
    session = request["session"] if "session" in request else p.DEFAULT_SESSION
    if not isinstance(session, str):
        raise p.BrowserError(p.invalid("session must be a string"))
    mode = request["mode"] if "mode" in request else None
    if mode not in (None, "standard", "stealth"):
        raise p.BrowserError(p.invalid("mode must be standard, stealth, or null"))
    raw_timeout = request["timeout_s"] if "timeout_s" in request else p.EXEC_TIMEOUT_DEFAULT_SECS
    if not isinstance(raw_timeout, int):
        raise p.BrowserError(p.invalid("timeout_s must be an integer"))
    timeout = min(max(raw_timeout, p.EXEC_TIMEOUT_MIN_SECS), p.EXEC_TIMEOUT_MAX_SECS)
    warnings = ["timeout_clamped"] if timeout != raw_timeout else []
    return session, tp.cast(p.Mode | None, mode), timeout, code, warnings


def _outcome_error(outcome: ExecOutcome, session: sessions_mod.Session) -> p.Error | None:
    if outcome.timed_out:
        return p.error(
            "timed_out",
            "execution",
            "execution exceeded its budget",
            retryable=True,
            suggested_action="raise --timeout (and the Bash timeout) or split the program",
        )
    if outcome.cancelled:
        return p.error("cancelled", "execution", "the client cancelled this request", retryable=False, suggested_action="rerun when ready")
    if outcome.capability_mismatch is not None:
        other = "chromium" if session.engine == "camoufox" else "camoufox"
        return p.error(
            "engine_capability_mismatch",
            "execution",
            f"{outcome.capability_mismatch}() is unavailable on {session.engine}",
            retryable=False,
            suggested_action=f"change the code to the portable helpers, or start a new {other} session under a new name",
        )
    if outcome.exit_code != 0:
        return p.error(
            "execution_failed",
            "execution",
            f"the program exited with {outcome.exit_code}",
            retryable=False,
            suggested_action="read output.stderr and fix the code",
        )
    return None


async def _run_exec(state: State, session: sessions_mod.Session, request_id: str, code: str, timeout: int) -> tuple[ExecOutcome, float]:
    """Spawns the engine exec as an owned, cancellable task. The `finally` is the one place session
    state is restored, so a cancellation, a timeout, or any other exception all leave the session
    usable again instead of stuck `busy`: only a Camoufox restart-needed outcome stays stopped.
    """
    assert session.runtime is not None
    engine = ENGINES[session.engine]
    started_at = time.time()
    task = asyncio.ensure_future(engine.exec_code(session.runtime, session, state.paths, code, timeout))
    state.inflight[request_id] = task
    outcome: ExecOutcome | None = None
    try:
        outcome = await task
        return outcome, started_at
    except asyncio.CancelledError:
        outcome = ExecOutcome("", "", None, int((time.time() - started_at) * 1000), cancelled=True)
        return outcome, started_at
    finally:
        state.inflight.pop(request_id, None)
        session.request_id = None
        needs_restart = outcome is not None and session.engine == "camoufox" and (outcome.timed_out or "worker_restarted" in outcome.warnings)
        if needs_restart:
            await stop_session(state.paths, session, force=True)
            state.restart_pending.add(session.name)
        else:
            sessions_mod.mark(session, "ready")
        sessions_mod.touch(state.table, session)


async def _finish_exec(
    state: State, session: sessions_mod.Session, request_id: str, outcome: ExecOutcome, started_at: float, warnings: list[str]
) -> p.Result:
    """Observes the page, collects artifacts, and builds the exec envelope from a terminal outcome."""
    engine = ENGINES[session.engine]
    page = await engine.observe(session.runtime) if session.runtime is not None else p.page_unavailable()
    found, artifact_warnings = artifacts.collect(session, outcome.stdout, started_at, now=p.now_iso)
    stdout, cut_out = p.truncate(outcome.stdout, p.STDOUT_CAP_BYTES)
    stderr, cut_err = p.truncate(outcome.stderr, p.STDERR_CAP_BYTES)
    warnings = [*warnings, *outcome.warnings, *artifact_warnings, *(["output_truncated"] if cut_out or cut_err else [])]
    err = _outcome_error(outcome, session)
    if err is not None:
        state.last_error = err
    return p.result(
        request_id=request_id,
        op="exec",
        ok=err is None,
        session=sessions_mod.info(session),
        page=page,
        output={"stdout": stdout, "stderr": stderr, "exit_code": outcome.exit_code, "duration_ms": outcome.duration_ms},
        artifacts=found,
        warnings=warnings,
        err=err,
    )


async def op_exec(state: State, request_id: str, request: dict[str, p.JsonValue]) -> p.Result:
    name, mode, timeout, code, warnings = _validate_exec(request)
    session = sessions_mod.resolve_session(state.table, name, mode)
    if session.state == "handed_over":
        raise p.BrowserError(
            p.error(
                "handover_in_use",
                "routing",
                f"session {name!r} is handed over to the user",
                retryable=True,
                suggested_action="wait for browser handover stop",
            )
        )
    if session.state in ("busy", "starting"):
        raise p.BrowserError(p.invalid(f"session {name!r} is {session.state}; retry once the current request finishes"))
    warnings += await ensure_running(state, session)
    sessions_mod.mark(session, "busy")
    session.request_id = request_id
    outcome, started_at = await _run_exec(state, session, request_id, code, timeout)
    return await _finish_exec(state, session, request_id, outcome, started_at, warnings)


async def op_cancel(state: State, request_id: str, request: dict[str, p.JsonValue]) -> p.Result:
    target = str(request["target_request_id"]) if "target_request_id" in request else ""
    task = state.inflight.pop(target, None)
    if task is None:
        return p.result(request_id=request_id, op="cancel", ok=True, data={"cancelled": False})
    task.cancel()
    return p.result(request_id=request_id, op="cancel", ok=True, data={"cancelled": True})


async def op_sessions(state: State, request_id: str, _request: dict[str, p.JsonValue]) -> p.Result:
    listing: p.JsonValue = [dict(sessions_mod.info(s)) for s in state.table.sessions.values()]
    return p.result(request_id=request_id, op="sessions", ok=True, data={"sessions": listing})


async def op_session_stop(state: State, request_id: str, request: dict[str, p.JsonValue]) -> p.Result:
    name = str(request["session"]) if "session" in request else ""
    if name not in state.table.sessions:
        raise p.BrowserError(p.invalid(f"unknown session {name!r}"))
    session = state.table.sessions[name]
    if not await stop_session(state.paths, session):
        raise p.BrowserError(p.invalid(f"session {name!r} is {session.state}; refusing to stop"))
    return p.result(request_id=request_id, op="session_stop", ok=True, data={"stopped": name})


async def op_stop_all(state: State, request_id: str, _request: dict[str, p.JsonValue]) -> p.Result:
    stopped: list[str] = []
    for session in state.table.sessions.values():
        was_stopped = session.state == "stopped"
        if await stop_session(state.paths, session) and not was_stopped:
            stopped.append(session.name)
    return p.result(request_id=request_id, op="stop_all", ok=True, data={"stopped": stopped})


async def _idle_sweep(state: State) -> None:
    """The daemon's one background loop: idle sessions every pass, artifacts once an hour. A pass
    that fails is logged and the loop goes on, because a dead sweep leaves browsers running for the
    life of the daemon with nothing saying so."""
    since_prune = 0.0
    while True:
        await asyncio.sleep(IDLE_SWEEP_SECS)
        try:
            for session in sessions_mod.idle_sessions(state.table, IDLE_STOP_SECS):
                logger.info("stopping idle session %s", session.name)
                await stop_session(state.paths, session)
            since_prune += IDLE_SWEEP_SECS
            if since_prune >= PRUNE_INTERVAL_SECS:
                since_prune = 0.0
                await asyncio.to_thread(artifacts.prune, state.paths)
        except Exception:
            logger.exception("idle sweep pass failed")


Handler = tp.Callable[[State, str, dict[str, p.JsonValue]], tp.Awaitable[p.Result]]


async def handle_request(state: State, request: dict[str, p.JsonValue]) -> p.Result:
    op = str(request["op"]) if "op" in request else ""
    request_id = ""
    try:
        if "request_id" not in request or not isinstance(request["request_id"], str) or not request["request_id"]:
            raise p.BrowserError(p.invalid("request_id must be a non-empty string"))
        request_id = request["request_id"]
        if "version" not in request or request["version"] != p.PROTOCOL_VERSION:
            raise p.BrowserError(p.invalid(f"unsupported protocol version; this daemon speaks {p.PROTOCOL_VERSION}"))
        if op not in HANDLERS:
            raise p.BrowserError(p.invalid(f"unknown op {op!r}"))
        return await HANDLERS[op](state, request_id, request)
    except p.BrowserError as exc:
        state.last_error = exc.err
        return p.result(request_id=request_id, op=op, ok=False, err=exc.err)
    except Exception as exc:
        logger.exception("unhandled error in op %r", op)
        err = p.error("execution_failed", "execution", f"internal error: {exc}", retryable=False, suggested_action="run: browser doctor")
        state.last_error = err
        return p.result(request_id=request_id, op=op, ok=False, err=err)


async def _handle_connection(state: State, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        line = await reader.readline()
    except asyncio.LimitOverrunError:
        line = b""
    try:
        request = json.loads(line) if line else {}
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        response = await handle_request(state, request)
    except (ValueError, KeyError) as exc:
        response = p.result(request_id="", op="", ok=False, err=p.invalid(f"unreadable request: {exc}"))
    writer.write((json.dumps(response) + "\n").encode())
    with contextlib.suppress(ConnectionError):
        await writer.drain()
    writer.close()


def _write_daemon_died(paths: Paths, reason: str) -> None:
    paths.notifications.mkdir(exist_ok=True)
    notif = {"source": "browser", "type": "daemon_died", "reason": reason, "timestamp": p.now_iso()}
    filename = f"{int(time.time() * 1e6)}-browser-daemon_died.json"
    tmp = paths.notifications / f"{filename}.tmp"
    tmp.write_text(json.dumps(notif))
    tmp.replace(paths.notifications / filename)


async def serve(paths: Paths) -> int:
    state = State(paths=paths, table=sessions_mod.load_table(paths))
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.socket.unlink(missing_ok=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def on_signal(signum: int) -> None:
        state.asked_to_stop = signum == signal.SIGTERM
        stop.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, on_signal, signum)
    # A SIGKILLed daemon leaves its route registered, and vestad would then proxy the next handover's
    # page to a port nothing serves. Deregistering here is the one place that route is reconciled;
    # vestad answers a route it does not have with a 404 and the helper exits 0.
    try:
        await gateway.deregister_service(handover.SERVICE, timeout=STARTUP_DEREGISTER_TIMEOUT_SECS)
    except gateway.GatewayError as exc:
        logger.info("no browser route to deregister at startup: %s", exc)
    old_umask = os.umask(0o177)
    try:
        server = await asyncio.start_unix_server(
            lambda r, w: _handle_connection(state, r, w), path=str(paths.socket), limit=p.REQUEST_MAX_BYTES
        )
    finally:
        os.umask(old_umask)
    await asyncio.to_thread(artifacts.prune, paths)
    sweep_task = asyncio.create_task(_idle_sweep(state))
    state.tasks.add(sweep_task)
    sweep_task.add_done_callback(state.tasks.discard)
    logger.info("browser daemon listening on %s", paths.socket)
    try:
        await stop.wait()
    finally:
        # server.close() first so no new connections land; shutdown() BEFORE wait_closed() because
        # wait_closed() blocks until every connection's handler returns, and an exec handler is
        # parked on its inflight task until shutdown() cancels it.
        server.close()
        await shutdown(state)
        await server.wait_closed()
        paths.socket.unlink(missing_ok=True)
        if not state.asked_to_stop:
            _write_daemon_died(paths, "signal")
    return 0


async def _stop_every_session(state: State, budget: float) -> None:
    """Every session torn down at once inside one budget, not one after another: a stop that is
    still running when the budget expires has its engine and display process groups killed, because
    the alternative is a browser or Xvfb orphaned by the SIGKILL that ends this daemon, still holding
    its profile lock or X socket."""
    sessions = list(state.table.sessions.values())
    if not sessions:
        return
    runtimes = [session.runtime for session in sessions]
    displays = [session.display for session in sessions]
    stops = [asyncio.ensure_future(stop_session(state.paths, session, force=True)) for session in sessions]
    _, pending = await asyncio.wait(stops, timeout=budget)
    if not pending:
        return
    for task in pending:
        task.cancel()
    stuck: list[asyncio.subprocess.Process] = []
    for task, runtime, session_display in zip(stops, runtimes, displays, strict=True):
        if task not in pending:
            continue
        if runtime is not None:
            stuck.append(runtime.process)
        if session_display is not None:
            stuck += [session_display.xvfb, session_display.openbox]
    await asyncio.gather(*[kill_group(process, KILL_GRACE_SECS) for process in stuck], *pending, return_exceptions=True)


async def shutdown(state: State) -> None:
    """Gives a handover back first, then cancels the idle sweep and every inflight exec, then
    force-stops every session.

    The handover goes first because it owns the stream and the task still building it: cancelling
    that task as part of the sweep would strand both, and the browser and display under them are the
    session's own, stopped below. It takes its slice out of the sessions' budget only when there is
    a handover to give back, and never all of it.
    """
    started = time.monotonic()
    await handover.shutdown(state, budget=HANDOVER_SHUTDOWN_SECS, gateway_timeout=SHUTDOWN_GATEWAY_TIMEOUT_SECS)
    spent = time.monotonic() - started
    for task in list(state.tasks):
        task.cancel()
    for task in list(state.tasks):
        with contextlib.suppress(asyncio.CancelledError):
            await task
    inflight = list(state.inflight.values())
    for task in inflight:
        task.cancel()
    if inflight:
        await asyncio.gather(*inflight, return_exceptions=True)
    await _stop_every_session(state, max(SHUTDOWN_BUDGET_SECS - spent, MIN_SESSION_BUDGET_SECS))


def ping(paths: Paths, timeout: float) -> bool:
    """Sync liveness probe: a daemon that answers `status` is up. Used by lifecycle readiness and the CLI."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(paths.socket))
            sock.sendall(json.dumps({"version": p.PROTOCOL_VERSION, "op": "status", "request_id": "ping"}).encode() + b"\n")
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
        return bool(data) and json.loads(data)["ok"] is True
    except (OSError, ValueError, KeyError):
        return False


async def request(paths: Paths, payload: dict[str, p.JsonValue]) -> p.Result:
    reader, writer = await asyncio.open_unix_connection(str(paths.socket), limit=p.REQUEST_MAX_BYTES * 4)
    writer.write((json.dumps(payload) + "\n").encode())
    await writer.drain()
    line = await reader.readline()
    writer.close()
    return json.loads(line)


HANDLERS: dict[str, Handler] = {
    "status": op_status,
    "engines": op_engines,
    "exec": op_exec,
    "cancel": op_cancel,
    "sessions": op_sessions,
    "session_stop": op_session_stop,
    "stop_all": op_stop_all,
    "doctor": doctor.op_doctor,
    "handover_start": handover.op_handover_start,
    "handover_status": handover.op_handover_status,
    "handover_stop": handover.op_handover_stop,
}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    return asyncio.run(serve(load_paths(os.environ, pl.Path.home())))
