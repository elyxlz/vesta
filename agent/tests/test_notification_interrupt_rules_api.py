"""Tests for notification_rules through the GET/PUT /config agent API endpoint."""

import datetime as dt

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import core.models as vm
from core import config as cfg
from core import notification_interrupt_policy as npn
from core.api import _config_get_handler, _config_put_handler


async def _client(tmp_path, monkeypatch):
    # Drive the store path through AGENT_DIR so config_store_path() (env-resolved) and config.data_dir
    # (from the built config) point at the same file the loop reads.
    monkeypatch.setenv("AGENT_DIR", str(tmp_path / "agent"))
    config = vm.VestaConfig()
    app = web.Application()
    app["config"] = config
    app.router.add_get("/config", _config_get_handler)
    app.router.add_put("/config", _config_put_handler)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client, config


def _notif(**fields) -> vm.Notification:
    base = {"timestamp": dt.datetime(2025, 1, 1), "source": "twitter", "type": "tweet"}
    base.update(fields)
    return vm.Notification.model_validate(base)


@pytest.mark.anyio
async def test_get_returns_empty_rules_when_unset(tmp_path, monkeypatch):
    client, _ = await _client(tmp_path, monkeypatch)
    try:
        resp = await client.get("/config")
        assert resp.status == 200
        assert (await resp.json())["notification_rules"] == []
    finally:
        await client.close()


@pytest.mark.anyio
async def test_put_then_get_round_trip_and_applies(tmp_path, monkeypatch):
    client, config = await _client(tmp_path, monkeypatch)
    try:
        resp = await client.put("/config", json={"notification_rules": [{"source": "twitter", "action": "pool"}]})
        assert resp.status == 200

        resp = await client.get("/config")
        rules = (await resp.json())["notification_rules"]
        assert rules[0]["source"] == "twitter"
        assert rules[0]["action"] == "pool"
        assert rules[0]["id"], "PUT must assign ids"

        # Persisted to the store for the loop to read, and it drives the decision.
        loaded = cfg.load_notification_rules(config)
        assert loaded[0].source == "twitter"
        assert npn.notif_disposition(_notif(), loaded) == "pool"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_put_invalid_action_is_400(tmp_path, monkeypatch):
    client, config = await _client(tmp_path, monkeypatch)
    try:
        resp = await client.put("/config", json={"notification_rules": [{"source": "x", "action": "nope"}]})
        assert resp.status == 400
        assert cfg.load_notification_rules(config) == []
    finally:
        await client.close()


@pytest.mark.anyio
async def test_put_rejects_core_source(tmp_path, monkeypatch):
    client, config = await _client(tmp_path, monkeypatch)
    try:
        resp = await client.put("/config", json={"notification_rules": [{"source": "core", "action": "pool"}]})
        assert resp.status == 400
        assert cfg.load_notification_rules(config) == []
    finally:
        await client.close()


@pytest.mark.anyio
async def test_put_invalid_regex_predicate_is_400(tmp_path, monkeypatch):
    client, config = await _client(tmp_path, monkeypatch)
    try:
        rule = {"match": [{"field": "x", "op": "regex", "value": "(unclosed"}], "action": "pool"}
        resp = await client.put("/config", json={"notification_rules": [rule]})
        assert resp.status == 400
        assert cfg.load_notification_rules(config) == []
    finally:
        await client.close()


@pytest.mark.anyio
async def test_rules_put_after_prefs_put_keeps_both(tmp_path, monkeypatch):
    client, config = await _client(tmp_path, monkeypatch)
    try:
        resp = await client.put("/config", json={"agent_personality": "warm"})
        assert resp.status == 200
        # A rules-only write must not wipe the personality pref saved above (store merge).
        resp = await client.put("/config", json={"notification_rules": [{"source": "twitter", "action": "pool"}]})
        assert resp.status == 200

        assert cfg.read_config_store()["agent_personality"] == "warm"
        assert cfg.load_notification_rules(config)[0].source == "twitter"
    finally:
        await client.close()
