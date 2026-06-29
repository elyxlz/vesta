"""Tests for the GET/PUT /config/notification-policy agent API endpoint."""

import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

import core.models as vm
from core import notification_interrupt_policy as npn
from core.api import (
    _config_notification_policy_get_handler,
    _config_notification_policy_put_handler,
    _notifications_static_defaults_handler,
)
from core.events import EventBus
from aiohttp import web


async def _client(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    app = web.Application()
    app["config"] = config
    app["event_bus"] = EventBus(data_dir=config.data_dir)
    app.router.add_get("/config/notification-policy", _config_notification_policy_get_handler)
    app.router.add_put("/config/notification-policy", _config_notification_policy_put_handler)
    app.router.add_get("/notifications/static-defaults", _notifications_static_defaults_handler)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client, config


@pytest.mark.anyio
async def test_get_returns_empty_policy_when_unset(tmp_path):
    client, _ = await _client(tmp_path)
    try:
        resp = await client.get("/config/notification-policy")
        assert resp.status == 200
        assert (await resp.json()) == {"rules": [], "defaults": []}
    finally:
        await client.close()


@pytest.mark.anyio
async def test_put_then_get_round_trip_and_persist(tmp_path):
    client, config = await _client(tmp_path)
    try:
        resp = await client.put("/config/notification-policy", json={"rules": [{"source": "twitter", "action": "pool"}]})
        assert resp.status == 200
        saved = (await resp.json())["rules"]
        assert saved[0]["id"], "PUT must assign ids"

        resp = await client.get("/config/notification-policy")
        rules = (await resp.json())["rules"]
        assert rules[0]["source"] == "twitter"
        assert rules[0]["action"] == "pool"

        # Persisted to disk for the loop to read.
        assert npn.load_rules(config)[0].source == "twitter"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_put_drops_a_core_notification_so_the_agent_learns(tmp_path):
    """The policy applies live (no restart), so a user edit would otherwise be invisible to the running
    agent. PUT drops a pooled source=core notification recapping the change."""
    client, config = await _client(tmp_path)
    try:
        await client.put("/config/notification-policy", json={"rules": [{"source": "twitter", "action": "pool"}]})
        files = list(config.notifications_dir.glob("*.json"))
        assert len(files) == 1
        notif = json.loads(files[0].read_text())
        assert notif["source"] == "core"
        assert notif["type"] == vm.TYPE_NOTIFICATION_POLICY_CHANGE
        assert notif["interrupt"] is False  # pooled — not worth preempting the agent
        assert "twitter" in notif["body"]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_put_one_section_preserves_the_other(tmp_path):
    client, config = await _client(tmp_path)
    try:
        await client.put("/config/notification-policy", json={"rules": [{"source": "twitter", "action": "pool"}]})
        # A defaults-only PUT must not wipe the rules saved above (independent section writes).
        resp = await client.put("/config/notification-policy", json={"defaults": [{"source": "outlook", "type": "message", "action": "pool"}]})
        assert resp.status == 200
        body = await resp.json()
        assert [rule["source"] for rule in body["rules"]] == ["twitter"]
        assert [default["source"] for default in body["defaults"]] == ["outlook"]
        assert npn.load_rules(config)[0].source == "twitter"
        assert npn.load_defaults(config)[0].source == "outlook"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_put_invalid_json_is_400(tmp_path):
    client, _ = await _client(tmp_path)
    try:
        resp = await client.put("/config/notification-policy", data="not json", headers={"Content-Type": "application/json"})
        assert resp.status == 400
    finally:
        await client.close()


@pytest.mark.anyio
async def test_put_without_any_section_is_400(tmp_path):
    client, _ = await _client(tmp_path)
    try:
        resp = await client.put("/config/notification-policy", json={"nope": 1})
        assert resp.status == 400
    finally:
        await client.close()


@pytest.mark.anyio
async def test_put_invalid_action_is_400(tmp_path):
    client, _ = await _client(tmp_path)
    try:
        resp = await client.put("/config/notification-policy", json={"rules": [{"source": "x", "action": "nope"}]})
        assert resp.status == 400
    finally:
        await client.close()


@pytest.mark.anyio
async def test_put_rejects_core_source(tmp_path):
    client, config = await _client(tmp_path)
    try:
        resp = await client.put(
            "/config/notification-policy",
            json={"rules": [{"source": "core", "action": "pool"}]},
        )
        assert resp.status == 400
        assert npn.load_rules(config) == []
    finally:
        await client.close()


def _notif(source, notif_type, interrupt):
    event = {"type": "notification", "source": source, "summary": "x", "notif_type": notif_type, "sender": "", "notif_id": ""}
    if interrupt is not None:
        event["interrupt"] = interrupt
    return event


@pytest.mark.anyio
async def test_static_defaults_aggregates_latest_per_source_type(tmp_path):
    client, _ = await _client(tmp_path)
    bus = client.app["event_bus"]
    try:
        # twitter/tweet's default changed over time -> the latest (interrupt=True) must win.
        bus.emit(_notif("twitter", "tweet", False))
        bus.emit(_notif("twitter", "tweet", True))
        bus.emit(_notif("calendar", "reminder", True))
        # core is exempt and a pre-feature event has no interrupt flag -> both excluded.
        bus.emit(_notif("core", "migration", True))
        bus.emit(_notif("legacy", "old", None))

        resp = await client.get("/notifications/static-defaults")
        assert resp.status == 200
        assert (await resp.json())["defaults"] == [
            {"source": "calendar", "type": "reminder", "interrupt": True},
            {"source": "twitter", "type": "tweet", "interrupt": True},
        ]
    finally:
        bus.close()
        await client.close()


@pytest.mark.anyio
async def test_static_defaults_empty_when_no_notifications(tmp_path):
    client, _ = await _client(tmp_path)
    try:
        resp = await client.get("/notifications/static-defaults")
        assert resp.status == 200
        assert (await resp.json()) == {"defaults": []}
    finally:
        client.app["event_bus"].close()
        await client.close()


@pytest.mark.anyio
async def test_default_overrides_get_empty_then_put_round_trip(tmp_path):
    client, config = await _client(tmp_path)
    try:
        resp = await client.get("/config/notification-policy")
        assert resp.status == 200
        assert (await resp.json())["defaults"] == []

        resp = await client.put(
            "/config/notification-policy",
            json={"defaults": [{"source": "outlook", "type": "message", "action": "pool"}]},
        )
        assert resp.status == 200
        assert (await resp.json())["defaults"] == [{"source": "outlook", "type": "message", "action": "pool"}]

        # Persisted to disk for the loop to read.
        assert npn.load_defaults(config)[0].source == "outlook"
    finally:
        client.app["event_bus"].close()
        await client.close()


@pytest.mark.anyio
async def test_default_overrides_put_core_source_is_400(tmp_path):
    client, _ = await _client(tmp_path)
    try:
        resp = await client.put(
            "/config/notification-policy",
            json={"defaults": [{"source": "core", "action": "pool"}]},
        )
        assert resp.status == 400
    finally:
        client.app["event_bus"].close()
        await client.close()
