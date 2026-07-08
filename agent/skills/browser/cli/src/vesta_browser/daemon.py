"""Per-session daemon holding a WebDriver BiDi websocket and relaying requests over a Unix socket.

Protocol (one JSON line each way):

  client -> daemon:
    {"method": "browsingContext.navigate", "params": {...}}   # raw BiDi
    {"meta": "drain_events"}                                   # control
    {"meta": "set_context", "context": "..."}
    {"meta": "context"}
    {"meta": "pending_dialog"}
    {"meta": "shutdown"}
    {"meta": "info"}

  daemon -> client:
    {"result": {...}} | {"error": "..."} | {"events": [...]}
    {"context": "..."} | {"dialog": {...}} | {"ok": true}
    {"info": {...}}

One daemon per BROWSER_SESSION name. Socket: /tmp/vesta-browser-<name>.sock

BiDi has no Runtime.enable-style leak to guard against, and browsing-context ids are
stable across the session, so the CDP daemon's per-target session juggling collapses
to a single current-context id the daemon injects where the command shape needs it.
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

from .bidi import BidiClient, BidiError

INTERNAL_URL_PREFIXES = (
    "about:",
    "moz-extension://",
    "chrome://",
    "resource://",
)

EVENT_BUFFER = 500
MARK_TIMEOUT_S = 2
SUBSCRIBED_EVENTS = (
    "browsingContext.load",
    "browsingContext.domContentLoaded",
    "browsingContext.userPromptOpened",
    "browsingContext.userPromptClosed",
    "log.entryAdded",
)

# BiDi places the target context differently per command; the daemon owns the
# current-context decision and injects it where the caller left it out.
_CTX_TOP = frozenset(
    {
        "browsingContext.navigate",
        "browsingContext.reload",
        "browsingContext.traverseHistory",
        "browsingContext.captureScreenshot",
        "browsingContext.activate",
        "browsingContext.close",
        "browsingContext.handleUserPrompt",
        "browsingContext.setViewport",
        "browsingContext.print",
        "input.performActions",
        "input.releaseActions",
        "input.setFiles",
    }
)
_CTX_TARGET = frozenset({"script.evaluate", "script.callFunction"})

_MARK_JS = "if(!document.title.startsWith('\U0001f7e2'))document.title='\U0001f7e2 '+document.title"


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


def resolve_ws_url() -> str:
    """Resolve the BiDi websocket URL. Set by `browser launch` (recorded ws) or an
    explicit VESTA_BROWSER_BIDI_WS for an externally running Camoufox."""
    if "VESTA_BROWSER_BIDI_WS" in os.environ and os.environ["VESTA_BROWSER_BIDI_WS"]:
        return os.environ["VESTA_BROWSER_BIDI_WS"]
    raise RuntimeError("VESTA_BROWSER_BIDI_WS must be set. Run `browser launch` first.")


class Daemon:
    def __init__(self) -> None:
        self.bidi: BidiClient | None = None
        self.context: str | None = None
        self.events: deque[dict] = deque(maxlen=EVENT_BUFFER)
        self.dialog: dict | None = None
        self.stop = asyncio.Event()
        self.ws_url = ""
        self._consumers: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        self.ws_url = resolve_ws_url()
        _log(f"connecting to {self.ws_url}")
        self.bidi = BidiClient()
        try:
            await self.bidi.connect(self.ws_url)
        except Exception as e:
            raise RuntimeError(f"BiDi WS handshake failed: {e}")
        self.context = await self.bidi.new_session()
        _log(f"session ready, context={self.context}")

        # Create every event queue before subscribing so no event arrives before its
        # consumer exists (the client only enqueues methods it has a queue for).
        for method in SUBSCRIBED_EVENTS:
            self.bidi.on_event(method)
        await self.bidi.send("session.subscribe", {"events": list(SUBSCRIBED_EVENTS)})
        for method in SUBSCRIBED_EVENTS:
            self._spawn_consumer(method)

    def _spawn_consumer(self, method: str) -> None:
        task = asyncio.create_task(self._consume(method))
        self._consumers.add(task)
        task.add_done_callback(self._consumers.discard)

    async def _consume(self, method: str) -> None:
        assert self.bidi is not None
        queue = self.bidi.on_event(method)
        while True:
            params = await queue.get()
            self.events.append({"method": method, "params": params})
            if method == "browsingContext.userPromptOpened":
                self.dialog = params
            elif method == "browsingContext.userPromptClosed":
                self.dialog = None
            elif method == "browsingContext.load":
                await self._mark_tab(params)

    async def _mark_tab(self, params: dict) -> None:
        assert self.bidi is not None
        if "context" not in params:
            return
        try:
            await asyncio.wait_for(
                self.bidi.send("script.evaluate", {"expression": _MARK_JS, "target": {"context": params["context"]}, "awaitPromise": False}),
                timeout=MARK_TIMEOUT_S,
            )
        except (TimeoutError, BidiError):
            # Tab-marking is cosmetic; never let it break event handling.
            pass

    async def handle(self, req: dict) -> dict:
        assert self.bidi is not None
        if "meta" in req:
            return await self._handle_meta(req)
        return await self._handle_bidi(req)

    async def _handle_meta(self, req: dict) -> dict:
        meta = req["meta"]
        if meta == "drain_events":
            out = list(self.events)
            self.events.clear()
            return {"events": out}
        if meta == "context":
            return {"context": self.context}
        if meta == "set_context":
            self.context = req["context"] if "context" in req else None
            return {"context": self.context}
        if meta == "pending_dialog":
            return {"dialog": self.dialog}
        if meta == "info":
            return {"info": {"ws_url": self.ws_url, "context": self.context, "event_count": len(self.events)}}
        if meta == "shutdown":
            self.stop.set()
            return {"ok": True}
        return {"error": f"unknown meta: {meta!r}"}

    async def _handle_bidi(self, req: dict) -> dict:
        assert self.bidi is not None
        method = req["method"]
        params = dict(req["params"]) if "params" in req and req["params"] else {}
        if method in _CTX_TOP and "context" not in params and self.context:
            params["context"] = self.context
        elif method in _CTX_TARGET and "target" not in params and self.context:
            params["target"] = {"context": self.context}
        try:
            return {"result": await self.bidi.send(method, params)}
        except BidiError as e:
            if e.code in ("no such frame", "no such node") and await self._rederive_context():
                if method in _CTX_TOP:
                    params["context"] = self.context
                elif method in _CTX_TARGET:
                    params["target"] = {"context": self.context}
                try:
                    return {"result": await self.bidi.send(method, params)}
                except BidiError as retry:
                    return {"error": str(retry)}
            return {"error": str(e)}

    async def _rederive_context(self) -> bool:
        """The current context closed (tab gone); adopt the first remaining one."""
        assert self.bidi is not None
        try:
            tree = await self.bidi.send("browsingContext.getTree", {})
        except BidiError:
            return False
        if not tree["contexts"]:
            return False
        self.context = tree["contexts"][0]["context"]
        _log(f"re-derived context={self.context}")
        return True


async def _serve(daemon: Daemon) -> None:
    sock = socket_path()
    Path(sock).unlink(missing_ok=True)

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
            Path(p).unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(run())
