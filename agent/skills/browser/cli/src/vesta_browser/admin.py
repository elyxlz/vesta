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

# Track Chrome PIDs per session so we can stop them later.
CHROME_PID_FILE_TMPL = "/tmp/vesta-browser-{name}.chrome-pid"
CDP_PORT_FILE_TMPL = "/tmp/vesta-browser-{name}.cdp-port"


def _session_name(name: str | None = None) -> str:
    return name or os.environ.get("BROWSER_SESSION", "default")


def _chrome_pid_file(name: str | None = None) -> Path:
    return Path(CHROME_PID_FILE_TMPL.format(name=_session_name(name)))


def _cdp_port_file(name: str | None = None) -> Path:
    return Path(CDP_PORT_FILE_TMPL.format(name=_session_name(name)))


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
    except Exception:
        return False


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
    except Exception:
        pass

    try:
        pid = int(Path(pid_file).read_text())
    except (FileNotFoundError, ValueError):
        pid = 0
    if pid:
        for _ in range(75):
            try:
                os.kill(pid, 0)
                time.sleep(0.2)
            except ProcessLookupError:
                break
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

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
    _chrome_pid_file(session).write_text(str(running.pid))
    _cdp_port_file(session).write_text(str(running.cdp_port))
    return running


def read_session_port(name: str | None = None) -> int | None:
    try:
        return int(_cdp_port_file(name).read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def read_session_chrome_pid(name: str | None = None) -> int | None:
    try:
        return int(_chrome_pid_file(name).read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def stop_chrome(name: str | None = None) -> None:
    """Terminate the Chrome process for a session, if we launched it."""
    session = _session_name(name)
    pid = read_session_chrome_pid(session)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(25):
                try:
                    os.kill(pid, 0)
                    time.sleep(0.2)
                except ProcessLookupError:
                    break
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        except ProcessLookupError:
            pass
    for p in (_chrome_pid_file(session), _cdp_port_file(session)):
        try:
            os.unlink(p)
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
                "No Chrome for this session. Run `browser launch` first, "
                "or set VESTA_BROWSER_CDP_WS to connect to a remote browser."
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
    raise RuntimeError(
        f"daemon {session!r} did not come up within {wait_s}s. Last log line: {tail or '(none)'}"
    )


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
    """Enumerate sessions we know about by scanning /tmp/vesta-browser-*.pid files."""
    out = []
    for pid_f in Path("/tmp").glob("vesta-browser-*.chrome-pid"):
        name = pid_f.name.removeprefix("vesta-browser-").removesuffix(".chrome-pid")
        try:
            chrome_pid = int(pid_f.read_text().strip())
            alive = _pid_alive(chrome_pid)
        except Exception:
            chrome_pid, alive = 0, False
        port = read_session_port(name)
        out.append(
            {
                "name": name,
                "chrome_pid": chrome_pid,
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
        restart_daemon(s["name"])
        stop_chrome(s["name"])


def shutdown(name: str | None = None) -> None:
    """Stop the daemon and Chrome for a single session, clean up state files."""
    session = _session_name(name)
    restart_daemon(session)
    stop_chrome(session)
    for path in (
        log_path(session),
        Path(f"/tmp/vesta-browser-{session}.refs.json"),
    ):
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass
