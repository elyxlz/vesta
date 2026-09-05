"""The standard route: one headless Chromium per session, one browser-use child per exec.

Chromium picks a free DevTools port and writes it to `<profile>/DevToolsActivePort`; the child gets
that port as `BU_CDP_URL`, so Browser Harness never launches a browser of its own. Browser Harness
spawns its own per-`BU_NAME` daemon under `BH_RUNTIME_DIR`, which lives in the session scratch dir
so the daemon here can find and stop it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pathlib as pl
import signal
import time
import urllib.request

from . import protocol as p
from .procs import KILL_GRACE_SECS, kill_group
from .runtime_paths import Paths
from .runtimes import ChromiumRuntime, ExecOutcome, HeadedDisplay
from .sessions import Session

CHROMIUM_READY_TIMEOUT_SECS = 30
READY_POLL_SECS = 0.1
PID_POLL_SECS = 0.05
OBSERVE_TIMEOUT_SECS = 5
HARNESS_STOP_GRACE_SECS = 3
BROWSER_STOP_GRACE_SECS = 5
# The harness daemon runs as `python -m browser_harness.daemon`, so its own argv is what proves the
# recorded pid is still that daemon.
HARNESS_MARKER = b"browser_harness"


def launch_argv(paths: Paths, session: Session, headed: HeadedDisplay | None = None) -> list[str]:
    display_flags = [f"--window-size={headed.width},{headed.height}", "--window-position=0,0"] if headed is not None else ["--headless=new"]
    return [
        str(paths.chromium_exe),
        *display_flags,
        "--no-sandbox",
        "--remote-debugging-port=0",
        f"--user-data-dir={session.profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-sync",
        "about:blank",
    ]


def _path() -> str:
    return os.environ["PATH"] if "PATH" in os.environ else "/usr/local/bin:/usr/bin:/bin"


def child_env(session: Session, port: int) -> dict[str, str]:
    return {
        "PATH": _path(),
        "HOME": str(pl.Path.home()),
        "LANG": os.environ["LANG"] if "LANG" in os.environ else "C.UTF-8",
        "TMPDIR": str(session.scratch_dir / "tmp"),
        "BH_RUNTIME_DIR": str(session.scratch_dir / "runtime"),
        "BH_TMP_DIR": str(session.scratch_dir / "tmp"),
        "BH_HOME": str(session.scratch_dir / "home"),
        "BU_NAME": session.name,
        "BU_CDP_URL": f"http://127.0.0.1:{port}",
        "BH_UPDATE_CHECK": "0",
        "BH_TELEMETRY": "0",
        "PYTHONUNBUFFERED": "1",
    }


def _browser_env(headed: HeadedDisplay | None) -> dict[str, str]:
    env = {"PATH": _path(), "HOME": str(pl.Path.home())}
    if headed is not None:
        env["DISPLAY"] = headed.display
    return env


def _unavailable(message: str) -> p.BrowserError:
    return p.BrowserError(p.error("engine_unavailable", "launch", message, retryable=True, suggested_action="run: browser doctor"))


def _fetch_json(url: str) -> p.JsonValue:
    with urllib.request.urlopen(url, timeout=OBSERVE_TIMEOUT_SECS) as response:
        return json.loads(response.read())


async def start(session: Session, paths: Paths, *, headed: HeadedDisplay | None = None) -> ChromiumRuntime:
    if not paths.chromium_exe.is_file():
        raise _unavailable(f"chromium binary missing at {paths.chromium_exe}")
    if not paths.browser_use_bin.is_file():
        raise _unavailable(f"browser-use executor missing at {paths.browser_use_bin}; run the SETUP.md uv sync step")
    for sub in ("tmp", "runtime", "home"):
        (session.scratch_dir / sub).mkdir(exist_ok=True)
    port_file = session.profile_dir / "DevToolsActivePort"
    port_file.unlink(missing_ok=True)
    process = await asyncio.create_subprocess_exec(
        *launch_argv(paths, session, headed),
        env=_browser_env(headed),
        start_new_session=True,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    deadline = time.monotonic() + CHROMIUM_READY_TIMEOUT_SECS
    exited: int | None = None
    try:
        while time.monotonic() < deadline:
            if process.returncode is not None:
                exited = process.returncode
                break
            if port_file.is_file():
                first = port_file.read_text().splitlines()
                if first and first[0].isdigit():
                    port = int(first[0])
                    try:
                        await asyncio.to_thread(_fetch_json, f"http://127.0.0.1:{port}/json/version")
                    except OSError:
                        pass
                    else:
                        return ChromiumRuntime(process=process, port=port)
            await asyncio.sleep(READY_POLL_SECS)
    except asyncio.CancelledError:
        await kill_group(process, BROWSER_STOP_GRACE_SECS)
        raise
    except Exception as exc:
        # Every other failure here (an unreadable port file, a DevTools answer that is not JSON)
        # leaves a browser running that nothing else holds a handle to.
        await kill_group(process, BROWSER_STOP_GRACE_SECS)
        raise _unavailable(f"chromium startup failed: {exc}") from exc
    await kill_group(process, BROWSER_STOP_GRACE_SECS)
    if exited is not None:
        raise _unavailable(f"chromium exited with {exited} during startup")
    raise _unavailable(f"chromium did not expose DevTools within {CHROMIUM_READY_TIMEOUT_SECS}s")


async def exec_code(runtime: ChromiumRuntime, session: Session, paths: Paths, code: str, timeout_s: int) -> ExecOutcome:
    started = time.monotonic()
    child = await asyncio.create_subprocess_exec(
        str(paths.browser_use_bin),
        env=child_env(session, runtime.port),
        cwd=str(session.artifact_dir),
        start_new_session=True,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(child.communicate(code.encode()), timeout_s)
    except TimeoutError:
        await kill_group(child, KILL_GRACE_SECS)
        return ExecOutcome("", "", None, int((time.monotonic() - started) * 1000), timed_out=True)
    except asyncio.CancelledError:
        await kill_group(child, KILL_GRACE_SECS)
        raise
    return ExecOutcome(out.decode(errors="replace"), err.decode(errors="replace"), child.returncode, int((time.monotonic() - started) * 1000))


async def observe(runtime: ChromiumRuntime) -> p.PageInfo:
    try:
        targets = await asyncio.to_thread(_fetch_json, f"http://127.0.0.1:{runtime.port}/json/list")
    except (OSError, ValueError):
        return p.page_unavailable()
    if not isinstance(targets, list):
        return p.page_unavailable()
    try:
        for target in targets:
            if isinstance(target, dict) and target["type"] == "page" and not str(target["url"]).startswith(("chrome://", "devtools://")):
                return {
                    "state": "ready",
                    "tab_id": str(target["id"]),
                    "url": str(target["url"]),
                    "title": str(target["title"]),
                    "observed_at": p.now_iso(),
                }
    except (KeyError, TypeError):
        return p.page_unavailable()
    return p.page_unavailable()


def _harness_pid(session: Session) -> int | None:
    record = session.scratch_dir / "runtime" / "bu.pid"
    if not record.is_file():
        return None
    text = record.read_text().strip()
    try:
        parsed = json.loads(text)
        return int(parsed["pid"]) if isinstance(parsed, dict) else int(text)
    except (ValueError, KeyError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _is_harness(pid: int) -> bool:
    """Whether the recorded pid is still the harness daemon that was recorded.

    The scratch dir outlives the container, so a record can name a pid the kernel has since handed
    to something else; signalling on the record alone would kill that stranger.
    """
    try:
        cmdline = pl.Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    return HARNESS_MARKER in cmdline


async def _await_exit(pid: int, grace: float) -> bool:
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        await asyncio.sleep(PID_POLL_SECS)
    return not _pid_alive(pid)


async def stop(runtime: ChromiumRuntime, session: Session) -> None:
    pid = _harness_pid(session)
    if pid is not None and _is_harness(pid):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
    else:
        pid = None
    await kill_group(runtime.process, BROWSER_STOP_GRACE_SECS)
    if pid is not None and not await _await_exit(pid, HARNESS_STOP_GRACE_SECS):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    (session.scratch_dir / "runtime" / "bu.pid").unlink(missing_ok=True)
    # A stale headed profile's software-render prefs must never leak into the next headless launch.
    (session.profile_dir / "user.js").unlink(missing_ok=True)
