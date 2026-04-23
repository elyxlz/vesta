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


def _session_name() -> str:
    return os.environ.get("BROWSER_SESSION", "default")


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
        pass


def _is_real_page(target: dict) -> bool:
    return target.get("type") == "page" and not target.get("url", "").startswith(INTERNAL_URL_PREFIXES)


def resolve_ws_url() -> str:
    """Resolve the CDP websocket URL to connect to.

    Priority:
      1. VESTA_BROWSER_CDP_WS (explicit override, e.g. remote browser)
      2. VESTA_BROWSER_CDP_PORT (local Chrome we launched)
      3. scan ports VESTA_BROWSER_CDP_PORT_START..+100 for a /json/version endpoint
    """
    if ws := os.environ.get("VESTA_BROWSER_CDP_WS"):
        return ws

    import urllib.request

    port_env = os.environ.get("VESTA_BROWSER_CDP_PORT")
    if port_env:
        port = int(port_env)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3) as r:
            data = json.loads(r.read())
        ws = data.get("webSocketDebuggerUrl", "")
        if not ws:
            raise RuntimeError(f"/json/version on port {port} returned no webSocketDebuggerUrl")
        return ws

    raise RuntimeError(
        "VESTA_BROWSER_CDP_PORT or VESTA_BROWSER_CDP_WS must be set. "
        "Run `browser launch` first."
    )


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
        for domain in ("Page", "DOM", "Runtime", "Network"):
            try:
                await asyncio.wait_for(
                    self.cdp.send_raw(f"{domain}.enable", session_id=self.session),
                    timeout=5,
                )
            except Exception as e:
                _log(f"enable {domain}: {e}")

        if os.environ.get("VESTA_BROWSER_NO_STEALTH") != "1":
            ua = await self._fetch_user_agent()
            await stealth.apply_to_session(self.cdp, self.session, ua=ua)
        return pages[0]

    async def _fetch_user_agent(self) -> str | None:
        port = os.environ.get("VESTA_BROWSER_CDP_PORT")
        if not port:
            return None
        import urllib.request

        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                return json.loads(r.read()).get("User-Agent") or None
        except Exception:
            return None

    async def start(self) -> None:
        self.ws_url = resolve_ws_url()
        _log(f"connecting to {self.ws_url}")
        self.cdp = CDPClient(self.ws_url)
        try:
            await self.cdp.start()
        except Exception as e:
            raise RuntimeError(f"CDP WS handshake failed: {e}")

        await self.attach_first_page()

        # Tap events: buffer everything, track dialog state, mark active tab.
        orig = self.cdp._event_registry.handle_event
        mark_js = "if(!document.title.startsWith('\U0001F7E2'))document.title='\U0001F7E2 '+document.title"

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
                        timeout=2,
                    )
                except Exception:
                    pass
            return await orig(method, params, session_id)

        self.cdp._event_registry.handle_event = tap

    async def handle(self, req: dict) -> dict:
        assert self.cdp is not None
        meta = req.get("meta")
        if meta == "drain_events":
            out = list(self.events)
            self.events.clear()
            return {"events": out}
        if meta == "session":
            return {"session_id": self.session}
        if meta == "set_session":
            self.session = req.get("session_id")
            if self.session:
                try:
                    await asyncio.wait_for(
                        self.cdp.send_raw("Page.enable", session_id=self.session),
                        timeout=3,
                    )
                except Exception:
                    pass
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

        method = req["method"]
        params = req.get("params") or {}
        # Browser-level Target.* calls must not carry a session.
        sid = None if method.startswith("Target.") else (req.get("session_id") or self.session)
        try:
            return {"result": await self.cdp.send_raw(method, params, session_id=sid)}
        except Exception as e:
            msg = str(e)
            if "Session with given id not found" in msg and sid == self.session and sid:
                _log(f"stale session {sid}, re-attaching")
                if await self.attach_first_page():
                    return {
                        "result": await self.cdp.send_raw(method, params, session_id=self.session)
                    }
            return {"error": msg}


async def _serve(daemon: Daemon) -> None:
    sock = socket_path()
    if os.path.exists(sock):
        os.unlink(sock)

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            if not line:
                return
            resp = await daemon.handle(json.loads(line))
            writer.write((json.dumps(resp, default=str) + "\n").encode())
            await writer.drain()
        except Exception as e:
            _log(f"conn: {e}")
            try:
                writer.write((json.dumps({"error": str(e)}) + "\n").encode())
                await writer.drain()
            except Exception:
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
