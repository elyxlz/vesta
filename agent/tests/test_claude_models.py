"""Tests for the live Claude model catalog edge module and its /provider/models handler."""

import json
import typing

import pytest
from aiohttp import web

import core.claude_models as cm
import core.config as cfg


def test_parse_models_maps_id_and_display_name():
    payload = {"data": [{"id": "claude-opus-5", "display_name": "Claude Opus 5"}]}
    result = cm.parse_models(payload)
    assert result == [{"slug": "claude-opus-5", "label": "Claude Opus 5", "author": "Anthropic"}]


def test_read_access_token_missing_file(tmp_path, monkeypatch):
    # read_claude_access_token delegates to config.read_claude_oauth, the one owner of parsing
    # CREDENTIALS_PATH, so the seam to patch is config's module-level path, not a module of our own.
    monkeypatch.setattr(cfg, "CREDENTIALS_PATH", tmp_path / "nope.json")
    assert cm.read_claude_access_token() is None


def test_read_access_token_reads_blob(tmp_path, monkeypatch):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok"}}))
    monkeypatch.setattr(cfg, "CREDENTIALS_PATH", path)
    assert cm.read_claude_access_token() == "tok"


@pytest.mark.anyio
async def test_provider_models_handler_409_when_unauthenticated(monkeypatch):
    import core.api as api_mod

    monkeypatch.setattr(api_mod.claude_models, "read_claude_access_token", lambda: None)

    class _Req:
        def __init__(self) -> None:
            self.app: dict[str, object] = {}

    resp = await api_mod._provider_models_handler(typing.cast("web.Request", _Req()))
    assert resp.status == 409
