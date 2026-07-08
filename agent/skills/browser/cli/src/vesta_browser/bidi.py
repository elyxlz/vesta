"""Raw WebDriver BiDi client over a WebSocket. No Playwright, no geckodriver.

BiDi is the W3C bidirectional protocol Camoufox's Firefox exposes on
`--remote-debugging-port`. Wire shape (JSON per frame):

  client -> server:  {"id": N, "method": "browsingContext.navigate", "params": {...}}
  server -> client:  {"id": N, "type": "success", "result": {...}}
                     {"id": N, "type": "error", "error": "...", "message": "..."}
                     {"type": "event", "method": "browsingContext.load", "params": {...}}

The request/id correlation and event fan-out mirror the CDP client this replaces,
so the daemon's loop is reused. Camoufox does not speak CDP (removed in FF141+),
and there is no `Runtime.enable`-style leak to guard against here.
"""

from __future__ import annotations

import asyncio
import json

import websockets


class BidiError(Exception):
    """A BiDi command returned {type: "error"}."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class BidiClient:
    def __init__(self) -> None:
        self._ws: websockets.ClientConnection | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict]] = {}
        self._event_queues: dict[str, asyncio.Queue[dict]] = {}
        self._reader: asyncio.Task[None] | None = None

    async def connect(self, ws_url: str) -> None:
        self._ws = await websockets.connect(ws_url, max_size=None)
        self._reader = asyncio.create_task(self._read_loop())
        self._reader.add_done_callback(self._on_reader_done)

    def _on_reader_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(exc)

    async def _read_loop(self) -> None:
        assert self._ws is not None
        async for raw in self._ws:
            message = json.loads(raw)
            if "id" in message:
                await self._resolve(message)
            elif message["type"] == "event":
                await self._dispatch_event(message)

    async def _resolve(self, message: dict) -> None:
        command_id = message["id"]
        if command_id not in self._pending:
            return
        future = self._pending.pop(command_id)
        if future.done():
            return
        if message["type"] == "error":
            future.set_exception(BidiError(message["error"], message["message"]))
        else:
            future.set_result(message["result"])

    async def _dispatch_event(self, message: dict) -> None:
        method = message["method"]
        if method in self._event_queues:
            await self._event_queues[method].put(message["params"])

    def on_event(self, method: str) -> asyncio.Queue[dict]:
        """Return (creating if needed) the queue that receives `method` events."""
        if method not in self._event_queues:
            self._event_queues[method] = asyncio.Queue()
        return self._event_queues[method]

    async def send(self, method: str, params: dict | None = None) -> dict:
        if self._ws is None:
            raise RuntimeError("bidi client not connected")
        self._next_id += 1
        command_id = self._next_id
        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._pending[command_id] = future
        await self._ws.send(json.dumps({"id": command_id, "method": method, "params": params or {}}))
        return await future

    async def new_session(self) -> str:
        """Open a session and return the first top-level browsing-context id."""
        await self.send("session.new", {"capabilities": {}})
        tree = await self.send("browsingContext.getTree", {})
        return tree["contexts"][0]["context"]

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
        if self._ws is not None:
            await self._ws.close()
