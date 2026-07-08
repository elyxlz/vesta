"""In-process fake WebDriver BiDi server for the fast test tier.

Faithful to the wire shape the real BiDi client depends on: id-correlated
success/error responses and pushed events. It implements just enough of the
protocol for transport, daemon, snapshot, and helper tests, mirroring how the
cc_sdk tests drive a fake claude rather than mocking the transport.
"""

from __future__ import annotations

import asyncio
import base64
import json

import websockets

# 1x1 transparent PNG.
_PNG_1X1 = base64.b64encode(
    base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )
).decode()


class FakeBidiServer:
    def __init__(self, snapshot_nodes: list[dict] | None = None) -> None:
        self.navigations: list[str] = []
        self.snapshot_nodes = snapshot_nodes or []
        self._server: websockets.Server | None = None
        self.url = ""

    async def start(self) -> str:
        self._server = await websockets.serve(self._handle, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}/session"
        return self.url

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, ws: websockets.ServerConnection) -> None:
        async for raw in ws:
            message = json.loads(raw)
            await self._respond(ws, message)

    async def _respond(self, ws: websockets.ServerConnection, message: dict) -> None:
        method = message["method"]
        params = message["params"]
        command_id = message["id"]
        if method == "session.new":
            result = {"sessionId": "fake-session", "capabilities": {}}
        elif method == "session.subscribe":
            result = {}
        elif method == "browsingContext.getTree":
            result = {"contexts": [{"context": "ctx-1", "url": "about:blank", "children": []}]}
        elif method == "browsingContext.navigate":
            self.navigations.append(params["url"])
            await self._send(ws, {"type": "success", "id": command_id, "result": {"navigation": "nav-1", "url": params["url"]}})
            await self._send(ws, {"type": "event", "method": "browsingContext.load", "params": {"context": params["context"], "url": params["url"]}})
            return
        elif method == "browsingContext.captureScreenshot":
            result = {"data": _PNG_1X1}
        elif method == "script.evaluate":
            result = self._evaluate(params)
        elif method == "input.performActions":
            result = {}
        elif method in ("storage.getCookies",):
            result = {"cookies": []}
        else:
            await self._send(ws, {"type": "error", "id": command_id, "error": "unknown command", "message": method})
            return
        await self._send(ws, {"type": "success", "id": command_id, "result": result})

    def _evaluate(self, params: dict) -> dict:
        expression = params["expression"]
        if "__vestaSnapshot" in expression:
            return {"type": "success", "result": {"type": "array", "value": self.snapshot_nodes}}
        if expression.strip() == "1+1":
            return {"type": "success", "result": {"type": "number", "value": 2}}
        return {"type": "success", "result": {"type": "undefined"}}

    async def _send(self, ws: websockets.ServerConnection, payload: dict) -> None:
        await ws.send(json.dumps(payload))
