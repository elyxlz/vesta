"""Daemon lifecycle: launch Chrome, ensure daemon is alive, restart, stop."""

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
from .launcher import RunningChrome, launch

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
    """Daemon is alive AND its CDP WS responds. Catches stale daemons."""
    if not daemon_alive(name):
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(socket_path(name))
        s.sendall(b'{"method":"Target.getTargets","params":{}}\n')
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
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


def launch_chrome(
    name: str | None = None,
    *,
    headless: bool = False,
    stealth: bool = False,
    no_sandbox: bool = False,
    user_data_dir: Path | None = None,
    executable: str | None = None,
    extra_args: list[str] | None = None,
    port: int | None = None,
) -> RunningChrome:
    """Launch Chrome for a session, record pid + port for later discovery."""
    session = _session_name(name)
    running = launch(
        port=port,
        user_data_dir=user_data_dir,
        headless=headless,
        stealth=stealth,
        no_sandbox=no_sandbox,
        executable=executable,
        extra_args=extra_args,
    )
    _session_file(session, "chrome-pid").write_text(str(running.pid))
    _session_file(session, "cdp-port").write_text(str(running.cdp_port))
    return running


def read_session_port(name: str | None = None) -> int | None:
    try:
        return int(_session_file(name, "cdp-port").read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def read_session_chrome_pid(name: str | None = None) -> int | None:
    return _read_pid(_session_file(name, "chrome-pid"))


def stop_chrome(name: str | None = None) -> None:
    """Terminate the Chrome process for a session, if we launched it."""
    session = _session_name(name)
    pid = read_session_chrome_pid(session)
    if pid:
        _terminate_pid(pid)
    for p in (_session_file(session, "chrome-pid"), _session_file(session, "cdp-port")):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def ensure_daemon(wait_s: float = 30.0, name: str | None = None) -> None:
    """Spawn the daemon if not already healthy. Self-heals stale daemons."""
    session = _session_name(name)
    if daemon_healthy(session):
        return
    if daemon_alive(session):
        restart_daemon(session)

    # Resolve WS URL before the daemon spawns: either VESTA_BROWSER_CDP_WS is set
    # explicitly, or we have a recorded port from a previous launch_chrome call.
    env = {**os.environ, "BROWSER_SESSION": session}
    if "VESTA_BROWSER_CDP_WS" not in env and "VESTA_BROWSER_CDP_PORT" not in env:
        port = read_session_port(session)
        if port is None:
            raise RuntimeError(
                "No Chrome for this session. Run `browser launch` first, or set VESTA_BROWSER_CDP_WS to connect to a remote browser."
            )
        env["VESTA_BROWSER_CDP_PORT"] = str(port)

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
    """Enumerate sessions we know about by scanning /tmp/vesta-browser-*.chrome-pid files."""
    out = []
    for pid_f in Path("/tmp").glob("vesta-browser-*.chrome-pid"):
        name = pid_f.name.removeprefix("vesta-browser-").removesuffix(".chrome-pid")
        chrome_pid = _read_pid(pid_f)
        alive = _pid_alive(chrome_pid) if chrome_pid else False
        port = read_session_port(name)
        out.append(
            {
                "name": name,
                "chrome_pid": chrome_pid or 0,
                "chrome_alive": alive,
                "cdp_port": port,
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
    """Stop the daemon and Chrome for a single session, clean up state files."""
    session = _session_name(name)
    restart_daemon(session)
    stop_chrome(session)
    for path in (Path(log_path(session)), _session_file(session, "refs.json")):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
