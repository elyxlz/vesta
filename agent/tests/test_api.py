"""Tests for the agent WS server."""

import asyncio
import json
import socket
import time
import weakref

import pytest
from aiohttp import ClientSession, WSMsgType, web

import core.models as vm
from core.api import _ws_handler, start_ws_server
from core.events import ChatEvent


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _start_server(event_bus):
    app = web.Application()
    app["event_bus"] = event_bus
    app["websockets"] = weakref.WeakSet()
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


# Regression: ws_runner.cleanup() used to sit on aiohttp's 60s default shutdown_timeout
# per open WS handler because _ws_handler had no shutdown signal. Each connected client
# (CLI + web + mobile) added another 60s wait. Now the app's on_shutdown closes them all.
SHUTDOWN_BUDGET_SEC = 3.0


@pytest.mark.anyio
async def test_runner_cleanup_completes_quickly_with_open_ws(event_bus, tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent", ws_port=_pick_port(), agent_token="test-token")
    runner = await start_ws_server(event_bus, config, host="127.0.0.1")
    base = f"http://127.0.0.1:{config.ws_port}"
    auth = {"X-Agent-Token": "test-token"}

    async with ClientSession() as session:
        sockets = [
            await session.ws_connect(f"{base}/ws?skip_history=1", headers=auth),
            await session.ws_connect(f"{base}/ws?skip_history=1", headers=auth),
            await session.ws_connect(f"{base}/ws?skip_history=1", headers=auth),
        ]
        await asyncio.sleep(0.05)  # give handlers time to register in app["websockets"]

        start = time.monotonic()
        await runner.cleanup()
        elapsed = time.monotonic() - start

        for ws in sockets:
            if not ws.closed:
                await ws.close()

    assert elapsed < SHUTDOWN_BUDGET_SEC, f"runner.cleanup() took {elapsed:.2f}s, expected < {SHUTDOWN_BUDGET_SEC}s"


@pytest.mark.anyio
async def test_close_all_websockets_sends_close_frame(event_bus, tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent", ws_port=_pick_port(), agent_token="test-token")
    runner = await start_ws_server(event_bus, config, host="127.0.0.1")
    base = f"http://127.0.0.1:{config.ws_port}"
    auth = {"X-Agent-Token": "test-token"}

    async with ClientSession() as session:
        ws = await session.ws_connect(f"{base}/ws?skip_history=1", headers=auth)
        await asyncio.sleep(0.05)

        cleanup_task = asyncio.create_task(runner.cleanup())
        try:
            msg = await asyncio.wait_for(ws.receive(), timeout=SHUTDOWN_BUDGET_SEC)
        finally:
            await cleanup_task

    assert msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING)
