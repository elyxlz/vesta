"""The stealth route: one supervised worker process per session, speaking JSON lines over pipes.

The worker (engines/camoufox/worker.py) owns the Camoufox browser in-process, so a timeout kills
the process group and the browser with it; the profile persists and the next exec restarts it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pathlib as pl
import time
import typing as tp

from . import protocol as p
from .presets import fit_to_screen, select_preset
from .procs import KILL_GRACE_SECS, kill_group, reaped_on_failure, spawn
from .runtime_paths import CAMOUFOX_FF_MAJOR, Paths
from .runtimes import CamoufoxRuntime, ExecOutcome, HeadedDisplay, elapsed_ms
from .sessions import Session

CAMOUFOX_READY_TIMEOUT_SECS = 90
WORKER_STOP_GRACE_SECS = 5
READY_LINE = {"ready": True}


async def _fail_startup(process: asyncio.subprocess.Process, message: str) -> tp.NoReturn:
    await kill_group(process, KILL_GRACE_SECS)
    raise p.BrowserError(p.unavailable(message)) from None


def _page_info(raw: p.JsonValue) -> p.PageInfo:
    if not isinstance(raw, dict):
        return p.page_unavailable()
    return p.page_ready(str(raw["tab_id"]), str(raw["url"]), str(raw["title"]))


def _is_ready_line(line: bytes) -> bool:
    try:
        return json.loads(line) == READY_LINE
    except ValueError:
        return False


def missing(paths: Paths) -> list[str]:
    """Every file the stealth route needs and this box does not have, each named with its path."""
    needed = (
        (paths.camoufox_python, "camoufox venv python"),
        (paths.camoufox_exe, "camoufox browser"),
        (paths.worker_script, "worker script"),
    )
    return [f"{label} missing at {path}" for path, label in needed if not path.is_file()]


def worker_argv(paths: Paths, session: Session, config_path: pl.Path, headed: HeadedDisplay) -> list[str]:
    return [
        str(paths.camoufox_python),
        str(paths.worker_script),
        "--profile",
        str(session.profile_dir),
        "--executable",
        str(paths.camoufox_exe),
        "--config",
        str(config_path),
        "--artifacts",
        str(session.artifact_dir),
        "--ff-version",
        str(CAMOUFOX_FF_MAJOR),
        "--window",
        f"{headed.width}x{headed.height}",
    ]


async def start(session: Session, paths: Paths, *, headed: HeadedDisplay) -> CamoufoxRuntime:
    gaps = missing(paths)
    if gaps:
        raise p.BrowserError(p.unavailable("; ".join(gaps)))
    config_path = session.scratch_dir / "camou-config.json"
    preset = select_preset(session.profile_dir)
    preset = fit_to_screen(preset, headed.width, headed.height)
    # The spoofed clock follows the agent's timezone; the preset's own zone stands only without TZ.
    if "TZ" in os.environ:
        preset = {**preset, "timezone": os.environ["TZ"]}
    # Camoufox's WebRender falls back to software rendering on Xvfb's dummy driver; without
    # these prefs the worker paints no frame at all on the session's display.
    (session.profile_dir / "user.js").write_text('user_pref("gfx.webrender.software", true);\nuser_pref("gfx.x11-glx.enabled", false);\n')
    config_path.write_text(json.dumps(preset))
    paths.log.parent.mkdir(parents=True, exist_ok=True)
    worker_env = {**os.environ, "DISPLAY": headed.display, "LIBGL_ALWAYS_SOFTWARE": "1"}
    # The worker's stderr is its whole diagnosis of a browser that would not come up; it belongs in
    # the daemon log beside everything else, never in /dev/null.
    with paths.log.open("ab") as log:
        process = await spawn(
            paths.children_ledger,
            *worker_argv(paths, session, config_path, headed),
            env=worker_env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=log,
        )
    if process.stdout is None:
        raise RuntimeError("camoufox worker has no pipe")
    try:
        async with reaped_on_failure(process, KILL_GRACE_SECS):
            line = await asyncio.wait_for(process.stdout.readline(), CAMOUFOX_READY_TIMEOUT_SECS)
    except TimeoutError:
        raise p.BrowserError(p.unavailable(f"camoufox worker did not report ready within {CAMOUFOX_READY_TIMEOUT_SECS}s")) from None
    except Exception as exc:
        raise p.BrowserError(p.unavailable(f"camoufox worker failed during startup: {exc}")) from exc
    if not line:
        await _fail_startup(process, f"camoufox worker exited during startup (code {process.returncode})")
    if not _is_ready_line(line):
        await _fail_startup(process, f"camoufox worker sent a malformed first line: {line[:80]!r}")
    return CamoufoxRuntime(process=process)


async def _ask(
    runtime: CamoufoxRuntime, payload: dict[str, p.JsonValue], timeout_s: float, expect: tuple[str, ...] = ()
) -> dict[str, p.JsonValue]:
    if runtime.process.stdin is None or runtime.process.stdout is None:
        raise RuntimeError("camoufox worker has no pipe")
    runtime.process.stdin.write((json.dumps(payload) + "\n").encode())
    await runtime.process.stdin.drain()
    line = await asyncio.wait_for(runtime.process.stdout.readline(), timeout_s)
    if not line:
        raise ConnectionError("camoufox worker closed its pipe")
    answer = json.loads(line)
    if not isinstance(answer, dict):
        raise ConnectionError("camoufox worker answered with a non-object")
    # The worker answers exec and observe with different key sets on one pipe that carries no
    # request id, so a reply read by the wrong waiter is a shape the caller never checks. Naming
    # the keys an op needs turns that into the garbled-pipe case the callers already recover from,
    # instead of an unhandled KeyError inside the caller.
    missing = [k for k in expect if k not in answer]
    if missing:
        raise ConnectionError(f"camoufox worker answered {payload.get('op')!r} without {', '.join(missing)}")
    return answer


async def exec_code(runtime: CamoufoxRuntime, _session: Session, _paths: Paths, code: str, timeout_s: int) -> ExecOutcome:
    started = time.monotonic()
    try:
        answer = await _ask(runtime, {"op": "exec", "code": code}, timeout_s, expect=("stdout", "stderr", "exit_code", "capability_mismatch"))
    except TimeoutError:
        await kill_group(runtime.process, KILL_GRACE_SECS)
        return ExecOutcome("", "", None, elapsed_ms(started), timed_out=True)
    except asyncio.CancelledError:
        await kill_group(runtime.process, KILL_GRACE_SECS)
        raise
    except (ConnectionError, ValueError) as exc:
        # A lost or garbled pipe is a worker this exec cannot trust: it is reaped here, and the
        # exit code it leaves is what queues the session's restart.
        await kill_group(runtime.process, KILL_GRACE_SECS)
        return ExecOutcome("", str(exc), None, elapsed_ms(started))
    mismatch = answer["capability_mismatch"]
    return ExecOutcome(
        str(answer["stdout"]),
        str(answer["stderr"]),
        int(str(answer["exit_code"])),
        elapsed_ms(started),
        capability_mismatch=str(mismatch) if isinstance(mismatch, str) else None,
    )


async def observe(runtime: CamoufoxRuntime) -> p.PageInfo:
    if runtime.process.returncode is not None:
        return p.page_unavailable()
    try:
        answer = await _ask(runtime, {"op": "observe"}, 5, expect=("page",))
    except (TimeoutError, ConnectionError, ValueError):
        return p.page_unavailable()
    return _page_info(answer["page"])


async def stop(runtime: CamoufoxRuntime, _session: Session) -> None:
    """The graceful ask is skipped for a worker that has already exited; the group kill is not,
    because a browser child can outlive the worker that owned it. A worker that answers the ask
    exits on its own once Firefox has closed, and that exit is awaited before the kill."""
    try:
        if runtime.process.returncode is None:
            with contextlib.suppress(TimeoutError, ConnectionError, ValueError):
                await _ask(runtime, {"op": "stop"}, WORKER_STOP_GRACE_SECS)
                await asyncio.wait_for(runtime.process.wait(), WORKER_STOP_GRACE_SECS)
    finally:
        await kill_group(runtime.process, WORKER_STOP_GRACE_SECS)
