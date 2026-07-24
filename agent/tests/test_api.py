"""Tests for the agent WS server."""

import asyncio
import json
import socket
import tempfile
import time
import typing
import weakref
from pathlib import Path

import pydantic as pyd
import pytest
from aiohttp import ClientSession, WSMsgType, web
from wait_util import wait_for_condition

import core.config as cfg
import core.models as vm
from core.api import _ws_handler, start_ws_server
from core.events import AssistantEvent


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _start_server(event_bus):
    app = web.Application()
    app["event_bus"] = event_bus
    app["config"] = cfg.VestaConfig(agent_dir=Path(tempfile.mkdtemp()) / "agent")
    app["state"] = vm.State()
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
async def test_ws_snapshot_omits_chat(event_bus):
    """The connect snapshot carries state + notifications + config, never chat: the app-chat skill owns
    chat end to end on its own service socket, so core neither transports nor seeds it."""
    runner, base = await _start_server(event_bus)
    try:
        async with ClientSession() as session, session.ws_connect(f"{base}/ws") as ws:
            msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
            data = json.loads(msg.data)
            assert data["type"] == "snapshot"
            assert "chat" not in data
            assert set(data) == {"type", "state", "notifications", "config"}
    finally:
        await runner.cleanup()


@pytest.mark.anyio
async def test_ws_snapshot_carries_agent_timezone(event_bus):
    """vestad reads the agent's IANA timezone off the connect snapshot to schedule
    auto-updates in the agent's local quiet window."""
    app = web.Application()
    app["event_bus"] = event_bus
    app["config"] = cfg.VestaConfig(agent_dir=Path(tempfile.mkdtemp()) / "agent", timezone="America/New_York")
    app["state"] = vm.State()
    app["websockets"] = weakref.WeakSet()
    app.router.add_get("/ws", _ws_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = _pick_port()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    try:
        async with ClientSession() as session, session.ws_connect(f"http://127.0.0.1:{port}/ws") as ws:
            msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
            data = json.loads(msg.data)
            assert data["type"] == "snapshot"
            assert data["config"]["timezone"] == "America/New_York"
    finally:
        await runner.cleanup()


@pytest.mark.anyio
async def test_ws_sends_empty_snapshot_when_no_events(event_bus):
    """The snapshot is always sent on connect, even with no events, so the client
    can distinguish 'still loading' from 'no messages' instead of guessing."""
    runner, base = await _start_server(event_bus)
    try:
        async with ClientSession() as session, session.ws_connect(f"{base}/ws") as ws:
            msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
            data = json.loads(msg.data)
            assert data["type"] == "snapshot"
            assert "chat" not in data
            assert data["notifications"]["pending"] == []
    finally:
        await runner.cleanup()


@pytest.mark.anyio
async def test_ws_recv_drain_survives_garbage_and_keeps_the_socket_live(event_bus):
    """Nothing injects events over the WS anymore: the recv loop is a pure drain. Inbound frames
    (garbage, a stale emit frame) are ignored without killing the connection, and the socket still
    receives bus events afterwards."""
    runner, base = await _start_server(event_bus)
    try:
        async with ClientSession() as session, session.ws_connect(f"{base}/ws") as ws:
            await asyncio.wait_for(ws.receive(), timeout=1.0)  # snapshot
            await ws.send_str("123")
            await ws.send_json({"type": "emit", "event": {"type": "chat", "id": 77, "text": "ignored"}})
            event_bus.emit(AssistantEvent(type="assistant", text="still alive"))
            received = await _drain_until(ws, lambda r: any(e.get("type") == "assistant" for e in r))
            assistants = [e for e in received if e.get("type") == "assistant"]
            assert [e["text"] for e in assistants] == ["still alive"]
            assert not any(e.get("type") == "chat" for e in received)
    finally:
        await runner.cleanup()


@pytest.mark.anyio
async def test_ws_snapshot_failure_cleans_up_subscription(event_bus, monkeypatch):
    """A snapshot-phase failure (before the recv/send loops exist) still runs the handler's finally
    cleanup: the bus subscription is dropped instead of a TypeError from gathering the not-yet-created
    tasks masking the original error and leaking the subscriber."""
    from core import api

    def _boom(config):
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr(api, "_pending_notification_ids", _boom)
    runner, base = await _start_server(event_bus)
    try:
        async with ClientSession() as session, session.ws_connect(f"{base}/ws") as ws:
            msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
            assert msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR)
        await wait_for_condition(lambda: len(event_bus._subscribers) == 0, message="subscriber leaked after snapshot failure")
    finally:
        await runner.cleanup()


@pytest.mark.anyio
async def test_send_loop_closes_on_eviction_sentinel(event_bus):
    """When the bus evicts a stalled subscriber (issue #1160) the send loop exits on the
    EvictedEvent so the handler closes the WS and the client reconnects for a fresh snapshot."""
    from core.api import _send_loop
    from core.events import EvictedEvent

    sent = []

    class _Ws:
        async def send_json(self, event):
            sent.append(event)

    sub = event_bus.subscribe()
    sub.put_nowait(EvictedEvent(type="evicted"))
    await asyncio.wait_for(_send_loop(typing.cast("web.WebSocketResponse", _Ws()), sub), timeout=1.0)
    assert sent == []


@pytest.mark.anyio
async def test_send_loop_closes_when_send_stalls(event_bus, monkeypatch):
    """A half-open socket whose send never completes is closed after the send timeout instead of
    lingering for minutes while its queue overflows (issue #1160)."""
    from core import api

    monkeypatch.setattr(api, "_SEND_TIMEOUT_S", 0.05)

    class _StalledWs:
        async def send_json(self, event):
            await asyncio.Event().wait()

    sub = event_bus.subscribe()
    event_bus.emit(AssistantEvent(type="assistant", text="never delivered"))
    await asyncio.wait_for(api._send_loop(typing.cast("web.WebSocketResponse", _StalledWs()), sub), timeout=1.0)


@pytest.mark.anyio
async def test_memory_put_writes_atomically(tmp_path):
    """PUT /memory lands the full content through the atomic tmp+rename writer, leaving no partial
    or leftover temp file behind."""
    from core.api import _memory_put_handler

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")

    class _Req:
        def __init__(self) -> None:
            self.app = {"config": config}

        async def json(self):
            return {"content": "remember me"}

    resp = await _memory_put_handler(typing.cast("web.Request", _Req()))
    assert resp.status == 200
    memory_path = tmp_path / "agent" / "MEMORY.md"
    assert memory_path.read_text() == "remember me"
    assert not memory_path.with_name(memory_path.name + ".tmp").exists()


# Regression: ws_runner.cleanup() used to sit on aiohttp's 60s default shutdown_timeout
# per open WS handler because _ws_handler had no shutdown signal. Each connected client
# (CLI + web + mobile) added another 60s wait. Now the app's on_shutdown closes them all.
SHUTDOWN_BUDGET_SEC = 3.0


@pytest.mark.anyio
async def test_runner_cleanup_completes_quickly_with_open_ws(event_bus, tmp_path):
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent", ws_port=_pick_port(), agent_token=pyd.SecretStr("test-token"))
    runner = await start_ws_server(event_bus, config, host="127.0.0.1")
    base = f"http://127.0.0.1:{config.ws_port}"
    auth = {"X-Agent-Token": "test-token"}

    async with ClientSession() as session:
        sockets = [
            await session.ws_connect(f"{base}/ws", headers=auth),
            await session.ws_connect(f"{base}/ws", headers=auth),
            await session.ws_connect(f"{base}/ws", headers=auth),
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
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent", ws_port=_pick_port(), agent_token=pyd.SecretStr("test-token"))
    runner = await start_ws_server(event_bus, config, host="127.0.0.1")
    base = f"http://127.0.0.1:{config.ws_port}"
    auth = {"X-Agent-Token": "test-token"}

    async with ClientSession() as session:
        ws = await session.ws_connect(f"{base}/ws", headers=auth)
        await wait_for_condition(lambda: len(runner.app["websockets"]) == 1, message="WS handler never registered")
        # Drain the connect snapshot (always sent) so the next frame is the close.
        await asyncio.wait_for(ws.receive(), timeout=SHUTDOWN_BUDGET_SEC)

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
    assert validate_config_updates(config, {"active_skills": ["whatsapp", "tasks", "tasks"]}) == {
        "active_skills": ["tasks", "whatsapp"],
    }
    assert validate_config_updates(config, {"log_level": "DEBUG", "response_timeout": 30}) == {
        "log_level": "DEBUG",
        "response_timeout": 30,
    }


def test_config_update_null_clears_a_key(config):
    from core.config import validate_config_updates

    # Nullable fields preserve null so the handler can clear the store key; list fields
    # canonicalize null to their empty value.
    assert validate_config_updates(config, {"nightly_memory_hour": None}) == {"nightly_memory_hour": None}
    assert validate_config_updates(config, {"active_skills": None}) == {"active_skills": []}


def test_config_update_rejects_unknown_field(config):
    from core.config import validate_config_updates

    with pytest.raises(ValueError):
        validate_config_updates(config, {"bogus": 1})


def test_config_update_rejects_bad_values(config):
    from core.config import validate_config_updates

    for bad in [
        {"nightly_memory_hour": 99},
        {"log_level": "LOUD"},
        {"active_skills": ["../core"]},
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
        def __init__(self) -> None:
            self.app = {"config": config}

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
    monkeypatch.setattr(api_mod, "clear_provider", lambda: signed_out)

    state = vm.State()
    state.provider_status = signed_out

    class _PutReq:
        def __init__(self) -> None:
            self.app = {"state": state, "config": config}

        async def json(self):
            return {"kind": "claude", "model": "opus", "credentials": "{}"}

    put_resp = await api_mod._provider_put_handler(typing.cast("web.Request", _PutReq()))
    assert put_resp.status == 200
    assert state.provider_status is signed_in

    class _DelReq:
        def __init__(self) -> None:
            self.app = {"state": state, "config": config}

    del_resp = await api_mod._provider_delete_handler(typing.cast("web.Request", _DelReq()))
    assert del_resp.status == 200
    assert state.provider_status is signed_out


@pytest.mark.anyio
async def test_status_reports_readiness_separate_from_provider(config):
    # /status carries the readiness gate (authed + setup_complete); /provider carries the config + authed
    # but NOT setup_complete (that's agent lifecycle, not the provider resource).
    import core.api as api_mod
    from core.config import update_config_store
    from core.provider import ProviderAuthState, ProviderStatus

    # A signed-in Claude agent: the chosen provider lives in the store, so /provider reports its kind.
    update_config_store({"provider": {"kind": "claude", "model": "opus"}})
    config = cfg.VestaConfig()
    state = vm.State()
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")
    state.persisted.first_start_done = True

    class _Req:
        def __init__(self) -> None:
            self.app = {"state": state, "config": config}

    status_resp = await api_mod._status_handler(typing.cast("web.Request", _Req()))
    assert json.loads(typing.cast("str", status_resp.text)) == {"authed": True, "provider_configured": True, "setup_complete": True}

    provider_resp = await api_mod._provider_get_handler(typing.cast("web.Request", _Req()))
    provider_body = json.loads(typing.cast("str", provider_resp.text))
    assert provider_body["authed"] is True
    assert "setup_complete" not in provider_body  # readiness moved to /status
    assert provider_body["kind"] == "claude"


@pytest.mark.anyio
async def test_provider_get_surfaces_claude_plan_tier():
    # The context picker gates >200K windows on the Max entitlement, so /provider surfaces the plan
    # tier read from the on-disk OAuth blob (which stored_config otherwise strips).
    import core.api as api_mod
    from core.config import ClaudeConfig, ClaudeOAuth
    from core.provider import ProviderAuthState, ProviderStatus

    config = cfg.VestaConfig.model_construct(provider=ClaudeConfig(oauth=ClaudeOAuth(subscriptionType="pro")))
    state = vm.State()
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")

    class _Req:
        def __init__(self) -> None:
            self.app = {"state": state, "config": config}

    resp = await api_mod._provider_get_handler(typing.cast("web.Request", _Req()))
    body = json.loads(typing.cast("str", resp.text))
    assert body["plan"] == "pro"


@pytest.mark.anyio
async def test_status_reports_unprovisioned_distinct_from_unauthenticated(config):
    # A fresh agent (no provider chosen) reports provider_configured=False, so vestad can show
    # "needs first sign-in" rather than "re-authenticate".
    import core.api as api_mod
    from core.provider import ProviderAuthState, ProviderStatus

    state = vm.State()
    state.provider_status = ProviderStatus(state=ProviderAuthState.NOT_AUTHENTICATED, kind="none", model=None)

    class _Req:
        def __init__(self) -> None:
            self.app = {"state": state, "config": config}

    status_resp = await api_mod._status_handler(typing.cast("web.Request", _Req()))
    assert json.loads(typing.cast("str", status_resp.text)) == {"authed": False, "provider_configured": False, "setup_complete": False}


@pytest.mark.anyio
async def test_history_q_returns_matching_events_in_history_shape(event_bus):
    # Search is folded into /history?q= and returns matching events in the same {events, cursor} shape
    # as recency (cursor null), replacing the old /search endpoint.
    from core.api import _history_handler

    event_bus.emit(AssistantEvent(type="assistant", text="what about paris"))
    event_bus.emit(AssistantEvent(type="assistant", text="paris is lovely"))
    event_bus.emit(AssistantEvent(type="assistant", text="london is grey"))

    app = web.Application()
    app["event_bus"] = event_bus
    app.router.add_get("/history", _history_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = _pick_port()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    try:
        async with ClientSession() as session, session.get(f"http://127.0.0.1:{port}/history?q=paris") as resp:
            assert resp.status == 200
            data = await resp.json()
        assert data["cursor"] is None
        texts = [e["text"] for e in data["events"]]
        assert "paris is lovely" in texts and "london is grey" not in texts
    finally:
        await runner.cleanup()


@pytest.mark.anyio
async def test_memory_put_rejects_non_dict_body(event_bus, tmp_path):
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent", ws_port=_pick_port(), agent_token=pyd.SecretStr("test-token"))
    runner = await start_ws_server(event_bus, config, host="127.0.0.1")
    base = f"http://127.0.0.1:{config.ws_port}"
    auth = {"X-Agent-Token": "test-token"}

    try:
        async with ClientSession() as session, session.put(f"{base}/memory", json=42, headers=auth) as resp:
            assert resp.status == 400
    finally:
        await runner.cleanup()


@pytest.mark.anyio
async def test_history_rejects_app_chat_channel_with_410(event_bus):
    """app-chat history moved to the app-chat skill service: core /history rejects channel=app-chat
    with 410 so a stale client fails loud rather than silently getting the full stream. Other channels
    are untouched."""
    from core.api import _history_handler

    app = web.Application()
    app["event_bus"] = event_bus
    app.router.add_get("/history", _history_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = _pick_port()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    try:
        async with ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/history?channel=app-chat") as resp:
                assert resp.status == 410
            async with session.get(f"http://127.0.0.1:{port}/history?channel=notifications") as resp:
                assert resp.status == 200
    finally:
        await runner.cleanup()
