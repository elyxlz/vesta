#!/usr/bin/env python3
"""Google Drive headless OAuth setup and status via rclone.

Flow (user on a phone, agent in a container, no shared browser):
  auth-start   runs `rclone authorize drive` in the background (loopback listener
               on 127.0.0.1:53682) and prints the Google sign-in URL for the user.
  auth-finish  takes the http://127.0.0.1:53682/?state=...&code=... URL the user
               pastes back, replays it to the local listener, captures the token
               and writes the [gdrive] remote into rclone.conf.
  status       checks the remote works.
  cancel       stops a pending auth listener.
"""

import base64
import configparser
import contextlib
import http.client
import json
import os
import pathlib as pl
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PORT = 53682
SCOPES = ("drive", "drive.readonly")
LOCAL_AUTH_RE = re.compile(r"http://127\.0\.0\.1:53682/auth\?state=\S+")
TOKEN_RE = re.compile(r"--->\s*(\S+?)\s*<---End paste", re.DOTALL)


def _extract_token(raw: str) -> str | None:
    """rclone prints the token as JSON (no config arg) or as a base64 config blob
    {"client_id","client_secret","token": "<json>"} (when a scope blob is passed)."""
    raw = raw.strip()
    if raw.startswith("{"):
        return raw
    try:
        blob = json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)))
        tok = blob.get("token")
        return tok if isinstance(tok, str) else json.dumps(tok)
    except Exception:
        return None


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ[name] if name in os.environ else default


def _data_dir() -> pl.Path:
    d = pl.Path(_env("GDRIVE_DATA_DIR", str(pl.Path.home() / ".gdrive")))
    d.mkdir(parents=True, exist_ok=True)
    d.chmod(0o700)
    return d


def _remote_name() -> str:
    return _env("GDRIVE_REMOTE_NAME", "gdrive")


def _die(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def _config_path() -> pl.Path:
    r = subprocess.run(["rclone", "config", "file"], capture_output=True, text=True, check=False)
    lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    if r.returncode != 0 or not lines:
        _die(f"could not locate rclone config: {r.stderr.strip()}")
    return pl.Path(lines[-1])


def _scope_blob(scope: str) -> str:
    """Base64 config blob for `rclone authorize drive <blob>`, padded so no '=' appears."""
    raw = json.dumps({"scope": scope})
    while len(raw) % 3:
        raw = raw[:-1] + " }"
    blob = base64.b64encode(raw.encode()).decode()
    assert "=" not in blob and "+" not in blob and "/" not in blob
    return blob


def _stop_pending() -> None:
    pid_file = _data_dir() / "authorize.pid"
    if not pid_file.exists():
        return
    with contextlib.suppress(ValueError, ProcessLookupError, PermissionError):
        os.killpg(int(pid_file.read_text().strip()), signal.SIGTERM)
    pid_file.unlink(missing_ok=True)
    time.sleep(0.5)


def _port_free() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", PORT)) != 0


def auth_start(scope: str) -> None:
    """Start the rclone loopback listener and print the Google sign-in URL."""
    if scope not in SCOPES:
        _die(f"scope must be one of {', '.join(SCOPES)}")
    _stop_pending()
    if not _port_free():
        _die(f"port {PORT} is busy. Run 'cancel' or kill the process holding it, then retry.")

    data = _data_dir()
    log_path = data / "authorize.log"
    log_path.unlink(missing_ok=True)
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    proc = subprocess.Popen(
        ["rclone", "authorize", "drive", _scope_blob(scope), "--auth-no-open-browser"],
        stdout=fd,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    os.close(fd)
    (data / "authorize.pid").write_text(str(proc.pid))
    (data / "authorize.scope").write_text(scope)

    local_url = None
    for _ in range(60):
        m = LOCAL_AUTH_RE.search(log_path.read_text())
        if m:
            local_url = m.group(0)
            break
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    if not local_url:
        _die(f"rclone authorize did not print a link. Log:\n{log_path.read_text()}")

    # The local /auth endpoint 307-redirects to Google. Grab the Location so the
    # user can open it directly on their phone (127.0.0.1 means nothing there).
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    try:
        conn.request("GET", local_url.removeprefix(f"http://127.0.0.1:{PORT}"))
        google_url = conn.getresponse().getheader("Location")
    finally:
        conn.close()
    if not google_url or "accounts.google.com" not in google_url:
        _die(f"unexpected redirect target: {google_url!r}")

    requested = urllib.parse.parse_qs(urllib.parse.urlparse(google_url).query).get("scope", [""])[0].split()
    if f"https://www.googleapis.com/auth/{scope}" not in requested:
        _stop_pending()
        _die(f"sign-in URL requests scopes {requested}, expected '{scope}'")

    print(f"Scope: {scope}")
    print("Send the user this link to open on their phone:\n")
    print(google_url)
    print(
        "\nAfter signing in and allowing access, the browser goes to a page that fails to load "
        "(http://127.0.0.1:53682/?state=...&code=...). That is expected. The user copies that full "
        "address from the address bar and sends it back. Then run:\n"
        f"  {sys.argv[0]} auth-finish '<pasted URL>'"
    )


def auth_finish(pasted: str) -> None:
    """Replay the pasted redirect URL to the local listener and save the token."""
    data = _data_dir()
    log_path = data / "authorize.log"
    if not (data / "authorize.pid").exists() or not log_path.exists():
        _die("no pending sign-in. Run 'auth-start' first.")

    u = urllib.parse.urlparse(pasted.strip())
    q = urllib.parse.parse_qs(u.query)
    if u.hostname not in ("127.0.0.1", "localhost") or u.port != PORT:
        _die(f"expected a URL starting with http://127.0.0.1:{PORT}/, got {pasted!r}")
    if "error" in q:
        _stop_pending()
        _die(f"Google returned an error: {q['error'][0]}. Run 'auth-start' again.")
    if "code" not in q or "state" not in q:
        _die("URL is missing code or state. Ask the user to copy the full address bar contents.")

    replay = f"http://127.0.0.1:{PORT}{u.path or '/'}?{u.query}"
    try:
        urllib.request.urlopen(replay, timeout=30).read()
    except urllib.error.HTTPError as e:
        print(f"Listener responded {e.code}; checking log", file=sys.stderr)
    except urllib.error.URLError as e:
        _die(f"local listener not reachable ({e.reason}). It may have timed out; run 'auth-start' again.")

    token = None
    for _ in range(120):
        m = TOKEN_RE.search(log_path.read_text())
        if m:
            token = _extract_token(m.group(1))
            break
        time.sleep(0.25)
    if not token:
        _die(f"no token captured (state mismatch or expired code?). Inspect {log_path} yourself; it may hold a token, never print it.")
    try:
        json.loads(token)
    except json.JSONDecodeError as e:
        _die(f"captured token is not valid JSON: {e}")

    scope_file = data / "authorize.scope"
    scope = scope_file.read_text().strip() if scope_file.exists() else "drive"
    _write_remote(scope, token)

    _stop_pending()
    log_path.unlink(missing_ok=True)
    scope_file.unlink(missing_ok=True)
    status()


def _write_remote(scope: str, token: str) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.optionxform = str
    if path.exists():
        cfg.read(path)
    name = _remote_name()
    cfg[name] = {"type": "drive", "scope": scope, "token": token, "team_drive": ""}
    with path.open("w") as f:
        cfg.write(f)
    path.chmod(0o600)
    print(f"Wrote [{name}] (scope {scope}) to {path}")


def status() -> None:
    """Check the remote works."""
    remote = f"{_remote_name()}:"
    r = subprocess.run(["rclone", "about", remote], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        _die(f"{remote} not working: {r.stderr.strip()}")
    print(f"{remote} OK\n{r.stdout.strip()}")


def cancel() -> None:
    """Stop a pending auth listener."""
    _stop_pending()
    data = _data_dir()
    for f in ("authorize.log", "authorize.scope"):
        (data / f).unlink(missing_ok=True)
    print("Pending sign-in cancelled")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["auth-start"]:
        scope = "drive"
        if len(args) == 3 and args[1] == "--scope":
            scope = args[2]
        elif len(args) != 1:
            _die("usage: auth-start [--scope drive|drive.readonly]")
        auth_start(scope)
    elif args[:1] == ["auth-finish"] and len(args) == 2:
        auth_finish(args[1])
    elif args == ["status"]:
        status()
    elif args == ["cancel"]:
        cancel()
    else:
        print(f"Usage: {sys.argv[0]} {{auth-start [--scope drive|drive.readonly], auth-finish <url>, status, cancel}}")
        sys.exit(1)
