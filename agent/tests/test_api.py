"""Tests for the agent WS server."""

import asyncio
import json
import socket

import pytest
from aiohttp import ClientSession, WSMsgType, web

from core.api import _ws_handler
from core.events import ChatEvent


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _start_server(event_bus):
    app = web.Application()
    app["event_bus"] = event_bus
    app.router.add_get("/ws", _ws_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = _pick_port()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    return runner, f"http://127.0.0.1:{port}"


async def _drain_until(ws, predicate, timeout=1.0):
    deadline = asyncio.get_event_loop().time() + timeout
    received = []
    while asyncio.get_event_loop().time() < deadline:
        remaining = max(0.01, deadline - asyncio.get_event_loop().time())
        try:
            msg = await asyncio.wait_for(ws.receive(), timeout=remaining)
        except TimeoutError:
            break
        if msg.type != WSMsgType.TEXT:
            break
        received.append(json.loads(msg.data))
        if predicate(received):
            break
    return received


@pytest.mark.anyio
async def test_ws_sends_history_by_default(event_bus):
    event_bus.emit(ChatEvent(type="chat", text="hello"))
    runner, base = await _start_server(event_bus)
    try:
        async with ClientSession() as session:
            async with session.ws_connect(f"{base}/ws") as ws:
                msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
                data = json.loads(msg.data)
                assert data["type"] == "history"
                assert any(e["type"] == "chat" and e["text"] == "hello" for e in data["events"])
    finally:
        await runner.cleanup()


@pytest.mark.anyio
async def test_ws_skip_history_omits_history_event(event_bus):
    event_bus.emit(ChatEvent(type="chat", text="stored"))
    runner, base = await _start_server(event_bus)
    try:
        async with ClientSession() as session:
            async with session.ws_connect(f"{base}/ws?skip_history=1") as ws:
                event_bus.emit(ChatEvent(type="chat", text="live"))
                received = await _drain_until(
                    ws,
                    lambda r: any(e.get("type") == "chat" and e.get("text") == "live" for e in r),
                )
                assert not any(e.get("type") == "history" for e in received)
                assert any(e.get("type") == "chat" and e.get("text") == "live" for e in received)
    finally:
        await runner.cleanup()
