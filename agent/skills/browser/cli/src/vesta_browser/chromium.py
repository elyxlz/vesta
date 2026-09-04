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
from .procs import kill_group
from .runtime_paths import Paths
from .runtimes import ChromiumRuntime, ExecOutcome
from .sessions import Session

CHROMIUM_READY_TIMEOUT_SECS = 30
READY_POLL_SECS = 0.1
OBSERVE_TIMEOUT_SECS = 5
HARNESS_STOP_GRACE_SECS = 3
BROWSER_STOP_GRACE_SECS = 5


def launch_argv(paths: Paths, session: Session) -> list[str]:
    return [
        str(paths.chromium_exe),
        "--headless=new",
        "--no-sandbox",
        "--remote-debugging-port=0",
        f"--user-data-dir={session.profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-sync",
        "about:blank",
    ]


def child_env(session: Session, port: int) -> dict[str, str]:
    return {
        "PATH": os.environ["PATH"] if "PATH" in os.environ else "/usr/local/bin:/usr/bin:/bin",
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


def _unavailable(message: str) -> p.BrowserError:
    return p.BrowserError(p.error("engine_unavailable", "launch", message, retryable=True, suggested_action="run: browser doctor"))


def _fetch_json(url: str) -> p.JsonValue:
    with urllib.request.urlopen(url, timeout=OBSERVE_TIMEOUT_SECS) as response:
        return json.loads(response.read())


async def start(session: Session, paths: Paths) -> ChromiumRuntime:
    if not paths.chromium_exe.is_file():
        raise _unavailable(f"chromium binary missing at {paths.chromium_exe}")
    if not paths.browser_use_bin.is_file():
        raise _unavailable(f"browser-use executor missing at {paths.browser_use_bin}; run the SETUP.md uv sync step")
    for sub in ("tmp", "runtime", "home"):
        (session.scratch_dir / sub).mkdir(exist_ok=True)
    port_file = session.profile_dir / "DevToolsActivePort"
    port_file.unlink(missing_ok=True)
    env = {"PATH": child_env(session, 0)["PATH"], "HOME": str(pl.Path.home())}
    process = await asyncio.create_subprocess_exec(
        *launch_argv(paths, session),
        env=env,
        start_new_session=True,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    deadline = time.monotonic() + CHROMIUM_READY_TIMEOUT_SECS
    try:
        while time.monotonic() < deadline:
            if process.returncode is not None:
                raise _unavailable(f"chromium exited with {process.returncode} during startup")
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
    await kill_group(process, BROWSER_STOP_GRACE_SECS)
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
        await kill_group(child, 1)
        return ExecOutcome("", "", None, int((time.monotonic() - started) * 1000), timed_out=True)
    except asyncio.CancelledError:
        await kill_group(child, 1)
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


async def stop(runtime: ChromiumRuntime, session: Session) -> None:
    pid = _harness_pid(session)
    if pid is not None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
        await asyncio.sleep(0)
    await kill_group(runtime.process, BROWSER_STOP_GRACE_SECS)
    if pid is not None:
        await asyncio.sleep(HARNESS_STOP_GRACE_SECS if _pid_alive(pid) else 0)
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
