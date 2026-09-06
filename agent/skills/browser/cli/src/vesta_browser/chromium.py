"""The standard route: one headed Chromium per session, on its own display, one browser-use child per exec.

Chromium picks a free DevTools port and writes it to `<profile>/DevToolsActivePort`; the child gets
that port as `BU_CDP_URL`, so Browser Harness never launches a browser of its own. Browser Harness
spawns its own per-`BU_NAME` daemon under `BH_RUNTIME_DIR`, which lives in the session scratch dir
so the daemon here can find and stop it.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import pathlib as pl
import signal
import time
import urllib.parse
import urllib.request

from . import display
from . import protocol as p
from .procs import KILL_GRACE_SECS, base_env, kill_group, reaped_on_failure
from .runtime_paths import Paths
from .runtimes import ChromiumRuntime, ExecOutcome, HeadedDisplay, elapsed_ms
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
# Chromium reads a SIGTERM exit as the OS ending its session and restores every tab on the next
# launch; pinning the startup pref to "open the new tab page" is what keeps a profile's tab count flat.
STARTUP_OPEN_NEW_TAB_PAGE = 5


def launch_argv(paths: Paths, session: Session, headed: HeadedDisplay) -> list[str]:
    return [
        str(paths.chromium_exe),
        f"--window-size={headed.width},{headed.height}",
        "--window-position=0,0",
        "--no-sandbox",
        # Docker's default /dev/shm is 64MB and the container sets no shm size; the renderer falls
        # back to /tmp instead of crashing the tab on a shared-memory-heavy page.
        "--disable-dev-shm-usage",
        "--remote-debugging-port=0",
        # Remote debugging alone flips navigator.webdriver to true, an automation tell every
        # anti-bot script reads; this keeps the flag at false, as it is in a person's own Chrome.
        "--disable-blink-features=AutomationControlled",
        # A page's WebRTC probe sees the public interface only, never the container's private address.
        "--force-webrtc-ip-handling-policy=default_public_interface_only",
        f"--user-data-dir={session.profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-sync",
        "about:blank",
    ]


def child_env(session: Session, port: int) -> dict[str, str]:
    return {
        **base_env(),
        "LANG": os.environ["LANG"] if "LANG" in os.environ else "C.UTF-8",
        "TMPDIR": str(session.scratch_dir / "tmp"),
        "BH_RUNTIME_DIR": str(session.scratch_dir / "runtime"),
        "BH_TMP_DIR": str(session.scratch_dir / "tmp"),
        "BH_HOME": str(session.scratch_dir / "home"),
        "BU_NAME": session.name,
        "BU_CDP_URL": f"http://127.0.0.1:{port}",
        "BH_UPDATE_CHECK": "0",
        "BH_TELEMETRY": "0",
        "BH_TAB_MARKER": "0",
        "PYTHONUNBUFFERED": "1",
    }


def _fetch_json(url: str) -> p.JsonValue:
    with urllib.request.urlopen(url, timeout=OBSERVE_TIMEOUT_SECS) as response:
        return json.loads(response.read())


def pin_startup_pref(profile_dir: pl.Path) -> None:
    prefs_path = profile_dir / "Default/Preferences"
    prefs: dict[str, p.JsonValue] = json.loads(prefs_path.read_text()) if prefs_path.is_file() else {}
    current = prefs["session"] if "session" in prefs else None
    prefs["session"] = {**(current if isinstance(current, dict) else {}), "restore_on_startup": STARTUP_OPEN_NEW_TAB_PAGE}
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(json.dumps(prefs))


def missing(paths: Paths) -> list[str]:
    """Every file the standard route needs and this box does not have, each named with its path."""
    needed = (
        (paths.chromium_exe, "chromium binary"),
        (paths.browser_use_bin, "browser-use executor (run the SETUP.md uv sync step)"),
    )
    return [f"{label} missing at {path}" for path, label in needed if not path.is_file()]


async def start(session: Session, paths: Paths, *, headed: HeadedDisplay) -> ChromiumRuntime:
    gaps = missing(paths)
    if gaps:
        raise p.BrowserError(p.unavailable("; ".join(gaps)))
    for sub in ("tmp", "runtime", "home"):
        (session.scratch_dir / sub).mkdir(exist_ok=True)
    port_file = session.profile_dir / "DevToolsActivePort"
    port_file.unlink(missing_ok=True)
    await asyncio.to_thread(pin_startup_pref, session.profile_dir)
    process = await asyncio.create_subprocess_exec(
        *launch_argv(paths, session, headed),
        env=display.child_env(headed.display),
        start_new_session=True,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    deadline = time.monotonic() + CHROMIUM_READY_TIMEOUT_SECS
    try:
        # Any failure here (an unreadable port file, a DevTools answer that is not JSON, a cancel)
        # would otherwise leave a browser running that nothing else holds a handle to.
        async with reaped_on_failure(process, BROWSER_STOP_GRACE_SECS):
            while time.monotonic() < deadline and process.returncode is None:
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
    except Exception as exc:
        raise p.BrowserError(p.unavailable(f"chromium startup failed: {exc}")) from exc
    await kill_group(process, BROWSER_STOP_GRACE_SECS)
    if process.returncode is not None:
        raise p.BrowserError(p.unavailable(f"chromium exited with {process.returncode} during startup"))
    raise p.BrowserError(p.unavailable(f"chromium did not expose DevTools within {CHROMIUM_READY_TIMEOUT_SECS}s"))


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
        return ExecOutcome("", "", None, elapsed_ms(started), timed_out=True)
    except asyncio.CancelledError:
        await kill_group(child, KILL_GRACE_SECS)
        raise
    return ExecOutcome(out.decode(errors="replace"), err.decode(errors="replace"), child.returncode, elapsed_ms(started))


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
                return p.page_ready(str(target["id"]), str(target["url"]), str(target["title"]))
    except (KeyError, TypeError):
        return p.page_unavailable()
    return p.page_unavailable()


def _harness_pid(session: Session) -> int | None:
    """The recorded harness pid, but only while it is still the harness daemon that was recorded.

    The scratch dir outlives the container, so a record can name a pid the kernel has since handed
    to something else; signalling on the record alone would kill that stranger.
    """
    record = session.scratch_dir / "runtime" / "bu.pid"
    if not record.is_file():
        return None
    text = record.read_text().strip()
    try:
        parsed = json.loads(text)
        pid = int(parsed["pid"]) if isinstance(parsed, dict) else int(text)
        cmdline = pl.Path(f"/proc/{pid}/cmdline").read_bytes()
    except (ValueError, KeyError, OSError):
        return None
    return pid if HARNESS_MARKER in cmdline else None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def _await_exit(pid: int, grace: float) -> bool:
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        await asyncio.sleep(PID_POLL_SECS)
    return not _pid_alive(pid)


def _masked_text_frame(payload: bytes) -> bytes:
    mask = os.urandom(4)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return bytes((0x81, 0x80 | len(payload))) + mask + masked


async def _close_over_cdp(runtime: ChromiumRuntime) -> None:
    """Asks the browser to close itself over its DevTools socket and waits for it to exit."""
    version = await asyncio.to_thread(_fetch_json, f"http://127.0.0.1:{runtime.port}/json/version")
    if not isinstance(version, dict):
        raise ValueError("DevTools /json/version is not an object")
    path = urllib.parse.urlsplit(str(version["webSocketDebuggerUrl"])).path
    reader, writer = await asyncio.open_connection("127.0.0.1", runtime.port)
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        writer.write(
            f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{runtime.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        await writer.drain()
        head = await reader.readuntil(b"\r\n\r\n")
        status = head.split(b" ", 2)
        if len(status) < 2 or status[1] != b"101":
            raise ConnectionError(f"DevTools refused the websocket upgrade: {head[:80]!r}")
        writer.write(_masked_text_frame(json.dumps({"id": 1, "method": "Browser.close"}).encode()))
        await writer.drain()
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
    await runtime.process.wait()


async def stop(runtime: ChromiumRuntime, session: Session) -> None:
    pid = _harness_pid(session)
    if pid is not None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
    # Chromium keeps cookies and storage in utility processes that batch their disk writes, and a
    # signal ends the browser before they flush, so a value set seconds earlier is lost; the CDP
    # close runs the browser's own shutdown, which writes them out first. The group kill that
    # follows reaps a straggler and is the fallback for a browser that ignores the close.
    with contextlib.suppress(OSError, EOFError, ValueError, KeyError, TimeoutError):
        await asyncio.wait_for(_close_over_cdp(runtime), BROWSER_STOP_GRACE_SECS)
    await kill_group(runtime.process, BROWSER_STOP_GRACE_SECS)
    if pid is not None and not await _await_exit(pid, HARNESS_STOP_GRACE_SECS):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    (session.scratch_dir / "runtime" / "bu.pid").unlink(missing_ok=True)
