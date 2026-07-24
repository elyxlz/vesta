"""Unit tests for the thin snapshot layer (the accname walker is vendored JS,
verified end-to-end in the live smoke)."""

from __future__ import annotations

import json

import pytest
from vesta_browser import snapshot


def _evaluate_ok(value_obj: dict) -> dict:
    """Shape of a daemon relay reply for a script.evaluate returning a JSON string."""
    return {"result": {"type": "success", "result": {"type": "string", "value": json.dumps(value_obj)}}}


def test_bundle_defines_walker_globals():
    src = snapshot._bundle()
    assert "__vestaSnapshot" in src
    assert "__vestaResolveRef" in src
    assert "__vestaFocusRef" in src


def test_snapshot_parses_walker_output(monkeypatch):
    payload = {
        "text": '- button "Go" [ref=e1]',
        "refs": {"e1": {"role": "button", "name": "Go"}},
        "ref_count": 1,
        "url": "https://x/",
        "title": "X",
    }

    def fake_send(req):
        if "meta" in req:
            return {"context": "ctx-1"}
        return _evaluate_ok(payload)

    monkeypatch.setattr(snapshot, "send", fake_send)
    snap = snapshot.snapshot()
    assert snap["ref_count"] == 1
    assert snap["refs"]["e1"]["role"] == "button"
    assert snap["title"] == "X"
    assert snap["url"] == "https://x/"
    assert snap["target_id"] == "ctx-1"
    assert "[ref=e1]" in snap["text"]


def test_snapshot_passes_opts_into_expression(monkeypatch):
    seen: dict = {}

    def fake_send(req):
        if "meta" in req:
            return {"context": "c"}
        seen["expr"] = req["params"]["expression"]
        return _evaluate_ok({"text": "", "refs": {}, "ref_count": 0, "url": "u", "title": "t"})

    monkeypatch.setattr(snapshot, "send", fake_send)
    snapshot.snapshot(interactive_only=True, max_depth=10)
    assert '"interactive_only": true' in seen["expr"]
    assert '"max_depth": 10' in seen["expr"]


def test_snapshot_raises_on_script_exception(monkeypatch):
    def fake_send(req):
        if "meta" in req:
            return {"context": ""}
        return {"result": {"type": "exception", "exceptionDetails": {"text": "walker boom"}}}

    monkeypatch.setattr(snapshot, "send", fake_send)
    with pytest.raises(RuntimeError, match="walker boom"):
        snapshot.snapshot()
