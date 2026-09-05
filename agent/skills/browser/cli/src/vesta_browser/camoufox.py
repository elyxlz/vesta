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
from .procs import KILL_GRACE_SECS, kill_group
from .runtime_paths import CAMOUFOX_FF_MAJOR, Paths
from .runtimes import CamoufoxRuntime, ExecOutcome, HeadedDisplay
from .sessions import Session

CAMOUFOX_READY_TIMEOUT_SECS = 90
WORKER_STOP_GRACE_SECS = 5


def _unavailable(message: str) -> p.BrowserError:
    return p.BrowserError(p.error("engine_unavailable", "launch", message, retryable=True, suggested_action="run: browser doctor"))


async def _fail_startup(process: asyncio.subprocess.Process, message: str) -> tp.NoReturn:
    await kill_group(process, KILL_GRACE_SECS)
    raise _unavailable(message) from None


def _page_info(raw: p.JsonValue) -> p.PageInfo:
    if not isinstance(raw, dict):
        return p.page_unavailable()
    return {"state": "ready", "tab_id": str(raw["tab_id"]), "url": str(raw["url"]), "title": str(raw["title"]), "observed_at": p.now_iso()}


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
    binaries = (
        (paths.camoufox_python, "camoufox venv python"),
        (paths.camoufox_exe, "camoufox browser"),
        (paths.worker_script, "worker script"),
    )
    for binary, label in binaries:
        if not binary.is_file():
            raise _unavailable(f"{label} missing at {binary}")
    config_path = session.scratch_dir / "camou-config.json"
    preset = select_preset(session.profile_dir)
    preset = fit_to_screen(preset, headed.width, headed.height)
    # Camoufox's WebRender falls back to software rendering on Xvfb's dummy driver; without
    # these prefs the worker paints no frame at all on the session's display.
    (session.profile_dir / "user.js").write_text('user_pref("gfx.webrender.software", true);\nuser_pref("gfx.x11-glx.enabled", false);\n')
    preset = {key: value for key, value in preset.items() if not key.startswith("_")}
    config_path.write_text(json.dumps(preset))
    paths.log.parent.mkdir(parents=True, exist_ok=True)
    worker_env = {**os.environ, "DISPLAY": headed.display, "LIBGL_ALWAYS_SOFTWARE": "1"}
    # The worker's stderr is its whole diagnosis of a browser that would not come up; it belongs in
    # the daemon log beside everything else, never in /dev/null.
    with paths.log.open("ab") as log:
        process = await asyncio.create_subprocess_exec(
            *worker_argv(paths, session, config_path, headed),
            start_new_session=True,
            env=worker_env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=log,
        )
    if process.stdout is None:
        raise RuntimeError("camoufox worker has no pipe")
    try:
        line = await asyncio.wait_for(process.stdout.readline(), CAMOUFOX_READY_TIMEOUT_SECS)
    except TimeoutError:
        await _fail_startup(process, f"camoufox worker did not report ready within {CAMOUFOX_READY_TIMEOUT_SECS}s")
    except asyncio.CancelledError:
        await kill_group(process, KILL_GRACE_SECS)
        raise
    except Exception as exc:
        await _fail_startup(process, f"camoufox worker failed during startup: {exc}")
    if not line:
        await _fail_startup(process, f"camoufox worker exited during startup (code {process.returncode})")
    try:
        ready = json.loads(line)
    except ValueError:
        await _fail_startup(process, f"camoufox worker sent a malformed first line: {line[:80]!r}")
    else:
        if ready != {"ready": True}:
            await _fail_startup(process, f"camoufox worker exited during startup (code {process.returncode})")
    return CamoufoxRuntime(process=process, config_path=config_path, last_page=p.page_unavailable())


async def _ask(runtime: CamoufoxRuntime, payload: dict[str, p.JsonValue], timeout_s: float) -> dict[str, p.JsonValue]:
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
    return answer


async def exec_code(runtime: CamoufoxRuntime, _session: Session, _paths: Paths, code: str, timeout_s: int) -> ExecOutcome:
    started = time.monotonic()
    try:
        answer = await _ask(runtime, {"op": "exec", "code": code}, timeout_s)
    except TimeoutError:
        await kill_group(runtime.process, KILL_GRACE_SECS)
        return ExecOutcome("", "", None, int((time.monotonic() - started) * 1000), timed_out=True)
    except asyncio.CancelledError:
        await kill_group(runtime.process, KILL_GRACE_SECS)
        raise
    except (ConnectionError, ValueError) as exc:
        await kill_group(runtime.process, KILL_GRACE_SECS)
        return ExecOutcome("", str(exc), None, int((time.monotonic() - started) * 1000), warnings=["worker_restarted"])
    runtime.last_page = _page_info(answer["page"])
    mismatch = answer["capability_mismatch"]
    return ExecOutcome(
        str(answer["stdout"]),
        str(answer["stderr"]),
        int(str(answer["exit_code"])),
        int((time.monotonic() - started) * 1000),
        capability_mismatch=str(mismatch) if isinstance(mismatch, str) else None,
    )


async def observe(runtime: CamoufoxRuntime) -> p.PageInfo:
    if runtime.process.returncode is not None:
        return p.page_unavailable()
    try:
        answer = await _ask(runtime, {"op": "observe"}, 5)
    except (TimeoutError, ConnectionError, ValueError):
        return p.page_unavailable()
    runtime.last_page = _page_info(answer["page"])
    return runtime.last_page


async def stop(runtime: CamoufoxRuntime, _session: Session) -> None:
    """The graceful ask is skipped for a worker that has already exited; the group kill is not,
    because a browser child can outlive the worker that owned it."""
    try:
        if runtime.process.returncode is None:
            with contextlib.suppress(TimeoutError, ConnectionError, ValueError):
                await _ask(runtime, {"op": "stop"}, WORKER_STOP_GRACE_SECS)
    finally:
        await kill_group(runtime.process, WORKER_STOP_GRACE_SECS)
