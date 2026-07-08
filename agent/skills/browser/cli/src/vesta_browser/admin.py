"""Daemon lifecycle: launch Camoufox, ensure daemon is alive, restart, stop."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from .daemon import log_path, pid_path, socket_path
from .launcher import RunningCamoufox, launch

SESSION_FILE_PREFIX = "/tmp/vesta-browser-"
GRACEFUL_EXIT_POLLS = 25
GRACEFUL_POLL_INTERVAL_S = 0.2


def _session_name(name: str | None = None) -> str:
    if name:
        return name
    return os.environ["BROWSER_SESSION"] if "BROWSER_SESSION" in os.environ else "default"


def _session_file(name: str | None, suffix: str) -> Path:
    return Path(f"{SESSION_FILE_PREFIX}{_session_name(name)}.{suffix}")


def daemon_alive(name: str | None = None) -> bool:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(socket_path(name))
        s.close()
        return True
    except (TimeoutError, FileNotFoundError, ConnectionRefusedError):
        return False


def daemon_healthy(name: str | None = None) -> bool:
    """Daemon is alive AND its BiDi WS responds. Catches stale daemons."""
    if not daemon_alive(name):
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(socket_path(name))
        s.sendall(b'{"method":"browsingContext.getTree","params":{}}\n')
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(1 << 16)
            if not chunk:
                break
            data += chunk
        s.close()
        return b'"result"' in data
    except (TimeoutError, OSError):
        return False


def _terminate_pid(pid: int) -> None:
    """SIGTERM then SIGKILL after a grace window. Best-effort — no-op if already dead."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(GRACEFUL_EXIT_POLLS):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(GRACEFUL_POLL_INTERVAL_S)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def restart_daemon(name: str | None = None) -> None:
    """Best-effort shutdown + socket/pid cleanup. Caller re-spawns via ensure_daemon()."""
    sock = socket_path(name)
    pid_file = pid_path(name)

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(sock)
        s.sendall(b'{"meta":"shutdown"}\n')
        s.recv(1024)
        s.close()
    except (TimeoutError, FileNotFoundError, ConnectionRefusedError, OSError):
        # Daemon may already be dead; cleanup below is still needed.
        pass

    pid = _read_pid(Path(pid_file))
    if pid:
        _terminate_pid(pid)

    for p in (sock, pid_file):
        Path(p).unlink(missing_ok=True)


def launch_browser(
    name: str | None = None,
    *,
    headless: bool = False,
    user_data_dir: Path | None = None,
    executable: str | None = None,
    extra_args: list[str] | None = None,
) -> RunningCamoufox:
    """Launch Camoufox for a session, record pid + BiDi ws url for later discovery."""
    session = _session_name(name)
    running = launch(
        user_data_dir=user_data_dir,
        headless=headless,
        executable=executable,
        extra_args=extra_args,
    )
    _session_file(session, "browser-pid").write_text(str(running.pid))
    _session_file(session, "bidi-ws").write_text(running.ws_url)
    return running


def read_session_ws_url(name: str | None = None) -> str | None:
    try:
        ws = _session_file(name, "bidi-ws").read_text().strip()
        return ws or None
    except FileNotFoundError:
        return None


def read_session_browser_pid(name: str | None = None) -> int | None:
    return _read_pid(_session_file(name, "browser-pid"))


def stop_browser(name: str | None = None) -> None:
    """Terminate the Camoufox process for a session, if we launched it."""
    session = _session_name(name)
    pid = read_session_browser_pid(session)
    if pid:
        _terminate_pid(pid)
    for p in (_session_file(session, "browser-pid"), _session_file(session, "bidi-ws")):
        p.unlink(missing_ok=True)


def ensure_daemon(wait_s: float = 30.0, name: str | None = None) -> None:
    """Spawn the daemon if not already healthy. Self-heals stale daemons."""
    session = _session_name(name)
    if daemon_healthy(session):
        return
    if daemon_alive(session):
        restart_daemon(session)

    # Resolve WS URL before the daemon spawns: either VESTA_BROWSER_BIDI_WS is set
    # explicitly, or we have a recorded ws url from a previous launch_browser call.
    env = {**os.environ, "BROWSER_SESSION": session}
    if "VESTA_BROWSER_BIDI_WS" not in env:
        ws_url = read_session_ws_url(session)
        if ws_url is None:
            raise RuntimeError(
                "No Camoufox for this session. Run `browser launch` first, or set VESTA_BROWSER_BIDI_WS to connect to a remote browser."
            )
        env["VESTA_BROWSER_BIDI_WS"] = ws_url

    proc = subprocess.Popen(
        [sys.executable, "-m", "vesta_browser.daemon"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.time() + wait_s
    while time.time() < deadline:
        if daemon_healthy(session):
            return
        if proc.poll() is not None:
            break
        time.sleep(0.2)

    tail = ""
    try:
        tail = Path(log_path(session)).read_text().splitlines()[-1]
    except (FileNotFoundError, IndexError):
        pass
    raise RuntimeError(f"daemon {session!r} did not come up within {wait_s}s. Last log line: {tail or '(none)'}")


def send(req: dict, name: str | None = None) -> dict:
    """Low-level sync request to the daemon. Raises on error."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(socket_path(name))
    s.sendall((json.dumps(req) + "\n").encode())
    data = b""
    while not data.endswith(b"\n"):
        chunk = s.recv(1 << 20)
        if not chunk:
            break
        data += chunk
    s.close()
    resp = json.loads(data)
    if "error" in resp:
        raise RuntimeError(resp["error"])
    return resp


def list_sessions() -> list[dict]:
    """Enumerate sessions we know about by scanning /tmp/vesta-browser-*.browser-pid files."""
    out = []
    for pid_f in Path("/tmp").glob("vesta-browser-*.browser-pid"):
        name = pid_f.name.removeprefix("vesta-browser-").removesuffix(".browser-pid")
        browser_pid = _read_pid(pid_f)
        alive = _pid_alive(browser_pid) if browser_pid else False
        out.append(
            {
                "name": name,
                "browser_pid": browser_pid or 0,
                "browser_alive": alive,
                "bidi_ws": read_session_ws_url(name),
                "daemon_alive": daemon_alive(name),
            }
        )
    return out


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def stop_all() -> None:
    """Stop every session this user has running."""
    for s in list_sessions():
        shutdown(s["name"])


def shutdown(name: str | None = None) -> None:
    """Stop the daemon and Camoufox for a single session, clean up state files."""
    session = _session_name(name)
    restart_daemon(session)
    stop_browser(session)
    Path(log_path(session)).unlink(missing_ok=True)
