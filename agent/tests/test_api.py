"""Tests for the agent WS server."""

import asyncio
import json
import socket
import time
import weakref

import pydantic as pyd
import pytest
from aiohttp import ClientSession, WSMsgType, web

import core.models as vm
from core.api import _ws_handler, start_ws_server
from core.events import ChatEvent, NotificationEvent, UserEvent
from wait_util import wait_for_condition


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
async def test_ws_sends_empty_history_when_no_events(event_bus):
    """The history event is always sent on connect, even with no events, so the client
    can distinguish 'still loading' from 'no messages' instead of guessing."""
    runner, base = await _start_server(event_bus)
    try:
        async with ClientSession() as session:
            async with session.ws_connect(f"{base}/ws") as ws:
                msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
                data = json.loads(msg.data)
                assert data["type"] == "history"
                assert data["events"] == []
                assert data["cursor"] is None
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


@pytest.mark.anyio
async def test_ws_history_survives_notification_storm(event_bus):
    """Regression: a burst of notifications used to fill the recent window and the
    seeded history rendered empty. The WS now seeds the app-chat channel, so the
    conversation comes through and notifications are excluded from history."""
    event_bus.emit(UserEvent(type="user", text="are you there"))
    event_bus.emit(ChatEvent(type="chat", text="i am here"))
    for i in range(200):
        event_bus.emit(NotificationEvent(type="notification", source="core", summary=f"spam {i}"))
    runner, base = await _start_server(event_bus)
    try:
        async with ClientSession() as session:
            async with session.ws_connect(f"{base}/ws") as ws:
                msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
                data = json.loads(msg.data)
                assert data["type"] == "history"
                history_types = {e["type"] for e in data["events"]}
                assert history_types == {"user", "chat"}
                assert any(e["type"] == "chat" and e["text"] == "i am here" for e in data["events"])
    finally:
        await runner.cleanup()


# Regression: ws_runner.cleanup() used to sit on aiohttp's 60s default shutdown_timeout
# per open WS handler because _ws_handler had no shutdown signal. Each connected client
# (CLI + web + mobile) added another 60s wait. Now the app's on_shutdown closes them all.
SHUTDOWN_BUDGET_SEC = 3.0


@pytest.mark.anyio
async def test_runner_cleanup_completes_quickly_with_open_ws(event_bus, tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent", ws_port=_pick_port(), agent_token=pyd.SecretStr("test-token"))
    runner = await start_ws_server(event_bus, config, host="127.0.0.1")
    base = f"http://127.0.0.1:{config.ws_port}"
    auth = {"X-Agent-Token": "test-token"}

    async with ClientSession() as session:
        sockets = [
            await session.ws_connect(f"{base}/ws?skip_history=1", headers=auth),
            await session.ws_connect(f"{base}/ws?skip_history=1", headers=auth),
            await session.ws_connect(f"{base}/ws?skip_history=1", headers=auth),
        ]
        await wait_for_condition(lambda: len(runner.app["websockets"]) == 3, message="WS handlers never registered")

        start = time.monotonic()
        await runner.cleanup()
        elapsed = time.monotonic() - start

        for ws in sockets:
            if not ws.closed:
                await ws.close()

    assert elapsed < SHUTDOWN_BUDGET_SEC, f"runner.cleanup() took {elapsed:.2f}s, expected < {SHUTDOWN_BUDGET_SEC}s"


@pytest.mark.anyio
async def test_close_all_websockets_sends_close_frame(event_bus, tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent", ws_port=_pick_port(), agent_token=pyd.SecretStr("test-token"))
    runner = await start_ws_server(event_bus, config, host="127.0.0.1")
    base = f"http://127.0.0.1:{config.ws_port}"
    auth = {"X-Agent-Token": "test-token"}

    async with ClientSession() as session:
        ws = await session.ws_connect(f"{base}/ws?skip_history=1", headers=auth)
        await wait_for_condition(lambda: len(runner.app["websockets"]) == 1, message="WS handler never registered")

        cleanup_task = asyncio.create_task(runner.cleanup())
        try:
            msg = await asyncio.wait_for(ws.receive(), timeout=SHUTDOWN_BUDGET_SEC)
        finally:
            await cleanup_task

    assert msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING)


# --- Request-body validation models (PUT /config, POST /provider) ---


def test_config_update_accepts_any_field_and_returns_sparse(config):
    from core.config import validate_config_updates

    # Any real config field may be set, by its VestaConfig name, not a fixed allow-list.
    assert validate_config_updates(config, {"agent_model": "sonnet"}) == {"agent_model": "sonnet"}
    assert validate_config_updates(config, {"log_level": "DEBUG", "response_timeout": 30}) == {
        "log_level": "DEBUG",
        "response_timeout": 30,
    }
    # thinking takes the plain string form; the model coerces it on load.
    assert validate_config_updates(config, {"thinking": "enabled"}) == {"thinking": "enabled"}


def test_config_update_null_clears_a_key(config):
    from core.config import validate_config_updates

    # A null is preserved (not dropped) so the handler can clear that key in the store.
    assert validate_config_updates(config, {"max_context_tokens": None}) == {"max_context_tokens": None}


def test_config_update_rejects_unknown_field(config):
    from core.config import validate_config_updates

    with pytest.raises(ValueError):
        validate_config_updates(config, {"bogus": 1})


def test_config_update_rejects_bad_values(config):
    from core.config import validate_config_updates

    for bad in [
        {"max_context_tokens": 0},
        {"nightly_memory_hour": 99},
        {"thinking": "x"},
        {"log_level": "LOUD"},
    ]:
        with pytest.raises(pyd.ValidationError):
            validate_config_updates(config, bad)


def test_provider_update_accepts_each_provider():
    from core.api import _ProviderUpdate

    assert _ProviderUpdate.model_validate({"credentials": "{}"}).credentials == "{}"
    parsed = _ProviderUpdate.model_validate({"openrouter_key": "k", "openrouter_model": "m"})
    assert (parsed.openrouter_key, parsed.openrouter_model) == ("k", "m")


def test_provider_update_requires_exactly_one_provider():

    from core.api import _ProviderUpdate

    for bad in [{}, {"credentials": "c", "openrouter_key": "k"}, {"openrouter_key": "k"}, {"bogus": 1}]:
        with pytest.raises(pyd.ValidationError):
            _ProviderUpdate.model_validate(bad)
