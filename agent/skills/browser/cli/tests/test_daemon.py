"""Unit tests for daemon control-flow that don't need a live BiDi connection."""

from __future__ import annotations

import asyncio

import pytest
from vesta_browser import daemon
from vesta_browser.bidi import BidiError


class RecordingBidi:
    """Minimal stand-in for BidiClient that records sends."""

    def __init__(self) -> None:
        self.sends: list[tuple[str, dict]] = []

    async def send(self, method: str, params: dict | None = None) -> dict:
        self.sends.append((method, params or {}))
        if method == "browsingContext.getTree":
            return {"contexts": [{"context": "ctx-new"}]}
        return {"ok": True}


def _daemon_with(context: str = "ctx-1") -> daemon.Daemon:
    d = daemon.Daemon()
    d.bidi = RecordingBidi()
    d.context = context
    return d


# ── Context injection ─────────────────────────────────────────


def test_handle_bidi_injects_top_level_context():
    d = _daemon_with("ctx-1")
    asyncio.run(d._handle_bidi({"method": "browsingContext.navigate", "params": {"url": "x"}}))
    _, params = d.bidi.sends[0]
    assert params["context"] == "ctx-1"


def test_handle_bidi_injects_script_target():
    d = _daemon_with("ctx-2")
    asyncio.run(d._handle_bidi({"method": "script.evaluate", "params": {"expression": "1"}}))
    _, params = d.bidi.sends[0]
    assert params["target"] == {"context": "ctx-2"}


def test_handle_bidi_respects_explicit_context():
    d = _daemon_with("ctx-1")
    asyncio.run(d._handle_bidi({"method": "browsingContext.navigate", "params": {"url": "x", "context": "explicit"}}))
    _, params = d.bidi.sends[0]
    assert params["context"] == "explicit"


def test_handle_bidi_no_injection_for_get_tree():
    d = _daemon_with("ctx-1")
    asyncio.run(d._handle_bidi({"method": "browsingContext.getTree", "params": {}}))
    _, params = d.bidi.sends[0]
    assert "context" not in params


# ── Stale-frame re-derivation ─────────────────────────────────


class FlakyBidi:
    def __init__(self) -> None:
        self.eval_calls = 0

    async def send(self, method: str, params: dict | None = None) -> dict:
        if method == "script.evaluate":
            self.eval_calls += 1
            if self.eval_calls == 1:
                raise BidiError("no such frame", "context is gone")
            return {"type": "success", "result": {"type": "undefined"}}
        if method == "browsingContext.getTree":
            return {"contexts": [{"context": "ctx-fresh"}]}
        return {"ok": True}


def test_handle_bidi_rederives_context_on_stale_frame():
    d = daemon.Daemon()
    d.bidi = FlakyBidi()
    d.context = "ctx-old"
    resp = asyncio.run(d._handle_bidi({"method": "script.evaluate", "params": {"expression": "1"}}))
    assert "result" in resp
    assert d.context == "ctx-fresh"


def test_handle_bidi_returns_error_on_plain_failure():
    class AlwaysFails:
        async def send(self, method, params=None):
            raise BidiError("invalid argument", "bad params")

    d = daemon.Daemon()
    d.bidi = AlwaysFails()
    d.context = "ctx-1"
    resp = asyncio.run(d._handle_bidi({"method": "browsingContext.navigate", "params": {"url": "x"}}))
    assert "error" in resp
    assert "bad params" in resp["error"]


# ── Meta control channel ──────────────────────────────────────


def test_meta_context_returns_current():
    d = _daemon_with("ctx-9")
    resp = asyncio.run(d._handle_meta({"meta": "context"}))
    assert resp == {"context": "ctx-9"}


def test_meta_set_context_updates():
    d = _daemon_with("ctx-1")
    resp = asyncio.run(d._handle_meta({"meta": "set_context", "context": "ctx-2"}))
    assert resp == {"context": "ctx-2"}
    assert d.context == "ctx-2"


def test_meta_drain_events_clears():
    d = _daemon_with()
    d.events.append({"method": "browsingContext.load", "params": {}})
    resp = asyncio.run(d._handle_meta({"meta": "drain_events"}))
    assert len(resp["events"]) == 1
    assert len(d.events) == 0


def test_meta_pending_dialog():
    d = _daemon_with()
    d.dialog = {"type": "alert", "message": "hi"}
    resp = asyncio.run(d._handle_meta({"meta": "pending_dialog"}))
    assert resp["dialog"]["message"] == "hi"


# ── WS URL resolution + session paths ─────────────────────────


def test_resolve_ws_url_uses_bidi_env(monkeypatch):
    monkeypatch.setenv("VESTA_BROWSER_BIDI_WS", "ws://custom/session")
    assert daemon.resolve_ws_url() == "ws://custom/session"


def test_resolve_ws_url_errors_when_unset(monkeypatch):
    monkeypatch.delenv("VESTA_BROWSER_BIDI_WS", raising=False)
    with pytest.raises(RuntimeError, match="VESTA_BROWSER_BIDI_WS"):
        daemon.resolve_ws_url()


def test_session_name_default(monkeypatch):
    monkeypatch.delenv("BROWSER_SESSION", raising=False)
    assert daemon._session_name() == "default"


def test_session_paths_use_session_name(monkeypatch):
    monkeypatch.setenv("BROWSER_SESSION", "agent-a")
    assert daemon.socket_path() == "/tmp/vesta-browser-agent-a.sock"
    assert daemon.pid_path() == "/tmp/vesta-browser-agent-a.pid"
    assert daemon.log_path() == "/tmp/vesta-browser-agent-a.log"


def test_session_paths_override_wins():
    assert daemon.socket_path("other") == "/tmp/vesta-browser-other.sock"
    assert daemon.pid_path("other") == "/tmp/vesta-browser-other.pid"
    assert daemon.log_path("other") == "/tmp/vesta-browser-other.log"
