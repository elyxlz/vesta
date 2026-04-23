"""Per-session daemon holding a CDP websocket and relaying requests over a Unix socket.

Protocol (one JSON line each way):

  client -> daemon:
    {"method": "Page.navigate", "params": {...}, "session_id": "..."}   # raw CDP
    {"meta": "drain_events"}                                             # control
    {"meta": "set_session", "session_id": "..."}
    {"meta": "session"}
    {"meta": "pending_dialog"}
    {"meta": "shutdown"}
    {"meta": "info"}

  daemon -> client:
    {"result": {...}} | {"error": "..."} | {"events": [...]}
    {"session_id": "..."} | {"dialog": {...}} | {"ok": true}
    {"info": {...}}

One daemon per BROWSER_SESSION name. Socket: /tmp/vesta-browser-<name>.sock
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import time
import urllib.request
from collections import deque
from pathlib import Path

from cdp_use.client import CDPClient  # type: ignore[import-untyped]

from . import stealth

INTERNAL_URL_PREFIXES = (
    "chrome://",
    "chrome-untrusted://",
    "devtools://",
    "chrome-extension://",
    "about:",
)

EVENT_BUFFER = 500
DOMAIN_ENABLE_TIMEOUT_S = 5
SESSION_REENABLE_TIMEOUT_S = 3
TAB_MARK_TIMEOUT_S = 2
UA_FETCH_TIMEOUT_S = 2
WS_DISCOVERY_TIMEOUT_S = 3


def _session_name() -> str:
    return os.environ["BROWSER_SESSION"] if "BROWSER_SESSION" in os.environ else "default"


def socket_path(name: str | None = None) -> str:
    return f"/tmp/vesta-browser-{name or _session_name()}.sock"


def pid_path(name: str | None = None) -> str:
    return f"/tmp/vesta-browser-{name or _session_name()}.pid"


def log_path(name: str | None = None) -> str:
    return f"/tmp/vesta-browser-{name or _session_name()}.log"


def _log(msg: str) -> None:
    try:
        with open(log_path(), "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        # Logging must never cascade. If the log file is unwritable we're already in trouble.
        pass


def _is_real_page(target: dict) -> bool:
    if "type" not in target or target["type"] != "page":
        return False
    url = target["url"] if "url" in target else ""
    return not url.startswith(INTERNAL_URL_PREFIXES)


def resolve_ws_url() -> str:
    """Resolve the CDP websocket URL to connect to.

    Priority:
      1. VESTA_BROWSER_CDP_WS (explicit override, e.g. remote browser)
      2. VESTA_BROWSER_CDP_PORT (local Chrome we launched)
    """
    if "VESTA_BROWSER_CDP_WS" in os.environ and os.environ["VESTA_BROWSER_CDP_WS"]:
        return os.environ["VESTA_BROWSER_CDP_WS"]

    if "VESTA_BROWSER_CDP_PORT" in os.environ:
        port = int(os.environ["VESTA_BROWSER_CDP_PORT"])
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=WS_DISCOVERY_TIMEOUT_S) as r:
            data = json.loads(r.read())
        if "webSocketDebuggerUrl" not in data or not data["webSocketDebuggerUrl"]:
            raise RuntimeError(f"/json/version on port {port} returned no webSocketDebuggerUrl")
        return data["webSocketDebuggerUrl"]

    raise RuntimeError("VESTA_BROWSER_CDP_PORT or VESTA_BROWSER_CDP_WS must be set. Run `browser launch` first.")


def _fetch_user_agent() -> str | None:
    if "VESTA_BROWSER_CDP_PORT" not in os.environ:
        return None
    port = os.environ["VESTA_BROWSER_CDP_PORT"]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=UA_FETCH_TIMEOUT_S) as r:
            data = json.loads(r.read())
    except (TimeoutError, OSError, json.JSONDecodeError) as e:
        _log(f"UA fetch failed: {e}")
        return None
    if "User-Agent" in data and data["User-Agent"]:
        return data["User-Agent"]
    return None


class Daemon:
    def __init__(self) -> None:
        self.cdp: CDPClient | None = None
        self.session: str | None = None
        self.events: deque[dict] = deque(maxlen=EVENT_BUFFER)
        self.dialog: dict | None = None
        self.stop = asyncio.Event()
        self.ws_url = ""

    async def attach_first_page(self) -> dict | None:
        assert self.cdp is not None
        targets = (await self.cdp.send_raw("Target.getTargets"))["targetInfos"]
        pages = [t for t in targets if _is_real_page(t)]
        if not pages:
            created = await self.cdp.send_raw("Target.createTarget", {"url": "about:blank"})
            target_id = created["targetId"]
            _log(f"no real pages, created about:blank tid={target_id}")
            pages = [{"targetId": target_id, "url": "about:blank", "type": "page"}]
        attach = await self.cdp.send_raw(
            "Target.attachToTarget",
            {"targetId": pages[0]["targetId"], "flatten": True},
        )
        self.session = attach["sessionId"]
        _log(f"attached target={pages[0]['targetId']} session={self.session}")

        async def _enable(domain: str) -> None:
            try:
                await asyncio.wait_for(
                    self.cdp.send_raw(f"{domain}.enable", session_id=self.session),
                    timeout=DOMAIN_ENABLE_TIMEOUT_S,
                )
            except (TimeoutError, RuntimeError) as e:
                _log(f"enable {domain}: {e}")

        await asyncio.gather(*(_enable(d) for d in ("Page", "DOM", "Runtime", "Network")))

        if "VESTA_BROWSER_NO_STEALTH" not in os.environ or os.environ["VESTA_BROWSER_NO_STEALTH"] != "1":
            ua = _fetch_user_agent()
            await stealth.apply_to_session(self.cdp, self.session, ua=ua)
        return pages[0]

    async def start(self) -> None:
        self.ws_url = resolve_ws_url()
        _log(f"connecting to {self.ws_url}")
        self.cdp = CDPClient(self.ws_url)
        try:
            await self.cdp.start()
        except Exception as e:
            raise RuntimeError(f"CDP WS handshake failed: {e}")

        await self.attach_first_page()

        orig = self.cdp._event_registry.handle_event
        mark_js = "if(!document.title.startsWith('\U0001f7e2'))document.title='\U0001f7e2 '+document.title"

        async def tap(method: str, params: dict, session_id: str | None = None):
            self.events.append({"method": method, "params": params, "session_id": session_id})
            if method == "Page.javascriptDialogOpening":
                self.dialog = params
            elif method == "Page.javascriptDialogClosed":
                self.dialog = None
            elif method in ("Page.loadEventFired", "Page.domContentEventFired"):
                try:
                    assert self.cdp is not None
                    await asyncio.wait_for(
                        self.cdp.send_raw(
                            "Runtime.evaluate",
                            {"expression": mark_js},
                            session_id=self.session,
                        ),
                        timeout=TAB_MARK_TIMEOUT_S,
                    )
                except (TimeoutError, RuntimeError):
                    # Tab-marking is cosmetic; don't let it kill event propagation.
                    pass
            return await orig(method, params, session_id)

        self.cdp._event_registry.handle_event = tap

    async def handle(self, req: dict) -> dict:
        assert self.cdp is not None
        if "meta" in req:
            return await self._handle_meta(req)
        return await self._handle_cdp(req)

    async def _handle_meta(self, req: dict) -> dict:
        meta = req["meta"]
        if meta == "drain_events":
            out = list(self.events)
            self.events.clear()
            return {"events": out}
        if meta == "session":
            return {"session_id": self.session}
        if meta == "set_session":
            self.session = req["session_id"] if "session_id" in req else None
            if self.session:
                try:
                    await asyncio.wait_for(
                        self.cdp.send_raw("Page.enable", session_id=self.session),
                        timeout=SESSION_REENABLE_TIMEOUT_S,
                    )
                except (TimeoutError, RuntimeError) as e:
                    _log(f"re-enable Page on new session: {e}")
            return {"session_id": self.session}
        if meta == "pending_dialog":
            return {"dialog": self.dialog}
        if meta == "info":
            return {
                "info": {
                    "ws_url": self.ws_url,
                    "session_id": self.session,
                    "event_count": len(self.events),
                }
            }
        if meta == "shutdown":
            self.stop.set()
            return {"ok": True}
        return {"error": f"unknown meta: {meta!r}"}

    async def _handle_cdp(self, req: dict) -> dict:
        method = req["method"]
        params = req["params"] if "params" in req and req["params"] else {}
        # Browser-level Target.* calls must not carry a session.
        if method.startswith("Target."):
            sid: str | None = None
        elif "session_id" in req and req["session_id"]:
            sid = req["session_id"]
        else:
            sid = self.session
        try:
            return {"result": await self.cdp.send_raw(method, params, session_id=sid)}
        except Exception as e:
            msg = str(e)
            if "Session with given id not found" in msg and sid == self.session and sid:
                _log(f"stale session {sid}, re-attaching")
                if await self.attach_first_page():
                    return {"result": await self.cdp.send_raw(method, params, session_id=self.session)}
            return {"error": msg}


async def _serve(daemon: Daemon) -> None:
    sock = socket_path()
    try:
        os.unlink(sock)
    except FileNotFoundError:
        pass

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            if not line:
                return
            resp = await daemon.handle(json.loads(line))
            writer.write((json.dumps(resp, default=str) + "\n").encode())
            await writer.drain()
        except (json.JSONDecodeError, ConnectionError, OSError) as e:
            _log(f"conn: {e}")
            try:
                writer.write((json.dumps({"error": str(e)}) + "\n").encode())
                await writer.drain()
            except (ConnectionError, OSError):
                pass
        finally:
            writer.close()

    server = await asyncio.start_unix_server(handler, path=sock)
    os.chmod(sock, 0o600)
    _log(f"listening on {sock}")
    async with server:
        await daemon.stop.wait()


async def _main() -> None:
    daemon = Daemon()
    await daemon.start()
    await _serve(daemon)


def _already_running() -> bool:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(socket_path())
        s.close()
        return True
    except (TimeoutError, FileNotFoundError, ConnectionRefusedError):
        return False


def run() -> int:
    """Entry point for the daemon process."""
    if _already_running():
        print(f"daemon already running on {socket_path()}", file=sys.stderr)
        return 0

    Path(log_path()).write_text("")
    Path(pid_path()).write_text(str(os.getpid()))

    try:
        asyncio.run(_main())
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        _log(f"fatal: {e}")
        return 1
    finally:
        for p in (socket_path(), pid_path()):
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    sys.exit(run())
