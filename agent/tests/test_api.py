"""Tests for the agent WS server."""

import asyncio
import json
import socket
import time
import typing
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


# --- Request-body validation for PUT /config (prefs + the auth sub-object) ---


def test_config_update_accepts_general_fields_and_returns_sparse(config):
    from core.config import validate_config_updates

    # Any general (non-provider-owned) config field may be set, by its VestaConfig name.
    assert validate_config_updates(config, {"agent_personality": "playful"}) == {"agent_personality": "playful"}
    assert validate_config_updates(config, {"log_level": "DEBUG", "response_timeout": 30}) == {
        "log_level": "DEBUG",
        "response_timeout": 30,
    }


def test_config_update_null_clears_a_key(config):
    from core.config import validate_config_updates

    # A null is preserved (not dropped) so the handler can clear that key in the store.
    assert validate_config_updates(config, {"nightly_memory_hour": None}) == {"nightly_memory_hour": None}


def test_config_update_rejects_unknown_field(config):
    from core.config import validate_config_updates

    with pytest.raises(ValueError):
        validate_config_updates(config, {"bogus": 1})


def test_config_update_rejects_bad_values(config):
    from core.config import validate_config_updates

    for bad in [
        {"nightly_memory_hour": 99},
        {"log_level": "LOUD"},
    ]:
        with pytest.raises(pyd.ValidationError):
            validate_config_updates(config, bad)


def test_config_update_rejects_bad_provider_values(config):
    from core.config import validate_config_updates

    # A provider partial keeps the field constraints (ge on context, the thinking union).
    for bad in [{"provider": {"max_context_tokens": 0}}, {"provider": {"thinking": "x"}}]:
        with pytest.raises(pyd.ValidationError):
            validate_config_updates(config, bad)


def test_sign_in_body_parses_each_provider():
    from core.api import _SIGN_IN_ADAPTER, _ClaudeSignIn, _OpenRouterSignIn

    claude = _SIGN_IN_ADAPTER.validate_python({"kind": "claude", "model": "opus", "credentials": "{}"})
    assert isinstance(claude, _ClaudeSignIn) and claude.credentials == "{}"
    openrouter = _SIGN_IN_ADAPTER.validate_python({"kind": "openrouter", "model": "m", "key": "k"})
    assert isinstance(openrouter, _OpenRouterSignIn) and (openrouter.key, openrouter.model) == ("k", "m")


def test_sign_in_body_rejects_invalid():
    from core.api import _SIGN_IN_ADAPTER

    for bad in [{}, {"kind": "claude"}, {"kind": "openrouter", "model": "m"}, {"kind": "vllm"}]:
        with pytest.raises(pyd.ValidationError):
            _SIGN_IN_ADAPTER.validate_python(bad)


@pytest.mark.anyio
async def test_config_put_rejects_a_provider_key(config):
    # The provider is set via /provider; a `provider` key in a /config (prefs) body is rejected.
    from core.api import _config_put_handler

    class _Req:
        app = {"config": config}

        async def json(self):
            return {"provider": {"model": "opus"}}

    resp = await _config_put_handler(typing.cast("web.Request", _Req()))
    assert resp.status == 400


@pytest.mark.anyio
async def test_provider_put_signs_in_then_delete_signs_out(config, monkeypatch):
    # PUT /provider applies credentials; DELETE /provider clears them. Each is write-only (the caller
    # restarts to apply), so the handlers just return ok.
    import core.api as api_mod
    from core.provider import ProviderAuthState, ProviderStatus

    signed_in = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")
    signed_out = ProviderStatus(state=ProviderAuthState.NOT_AUTHENTICATED, kind="none", model=None)
    monkeypatch.setattr(api_mod, "set_claude", lambda creds, model, ctx, *, config: signed_in)
    monkeypatch.setattr(api_mod, "clear_provider", lambda *, config: signed_out)

    state = vm.State()
    state.provider_status = signed_out

    class _PutReq:
        app = {"state": state, "config": config}

        async def json(self):
            return {"kind": "claude", "model": "opus", "credentials": "{}"}

    put_resp = await api_mod._provider_put_handler(typing.cast("web.Request", _PutReq()))
    assert put_resp.status == 200
    assert state.provider_status is signed_in

    class _DelReq:
        app = {"state": state, "config": config}

    del_resp = await api_mod._provider_delete_handler(typing.cast("web.Request", _DelReq()))
    assert del_resp.status == 200
    assert state.provider_status is signed_out


@pytest.mark.anyio
async def test_status_reports_readiness_separate_from_provider(config):
    # /status carries the readiness gate (authed + setup_complete); /provider carries the config + authed
    # but NOT setup_complete (that's agent lifecycle, not the provider resource).
    import core.api as api_mod
    from core.provider import ProviderAuthState, ProviderStatus

    state = vm.State()
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")
    state.persisted.first_start_done = True

    class _Req:
        app = {"state": state, "config": config}

    status_resp = await api_mod._status_handler(typing.cast("web.Request", _Req()))
    assert json.loads(typing.cast("str", status_resp.text)) == {"authed": True, "setup_complete": True}

    provider_resp = await api_mod._provider_get_handler(typing.cast("web.Request", _Req()))
    provider_body = json.loads(typing.cast("str", provider_resp.text))
    assert provider_body["authed"] is True
    assert "setup_complete" not in provider_body  # readiness moved to /status
    assert provider_body["kind"] == "claude"


@pytest.mark.anyio
async def test_history_q_returns_matching_events_in_history_shape(event_bus):
    # Search is folded into /history?q= and returns matching events in the same {events, cursor} shape
    # as recency (cursor null), replacing the old /search endpoint.
    from core.api import _history_handler

    event_bus.emit(UserEvent(type="user", text="what about paris"))
    event_bus.emit(ChatEvent(type="chat", text="paris is lovely"))
    event_bus.emit(ChatEvent(type="chat", text="london is grey"))

    app = web.Application()
    app["event_bus"] = event_bus
    app.router.add_get("/history", _history_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = _pick_port()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    try:
        async with ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/history?q=paris") as resp:
                assert resp.status == 200
                data = await resp.json()
        assert data["cursor"] is None
        texts = [e["text"] for e in data["events"]]
        assert "paris is lovely" in texts and "london is grey" not in texts
    finally:
        await runner.cleanup()
