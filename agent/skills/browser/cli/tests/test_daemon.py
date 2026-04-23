"""Unit tests for daemon helpers that don't need a live CDP connection."""

from __future__ import annotations

import pytest

from vesta_browser import daemon


def test_is_real_page_accepts_http():
    assert daemon._is_real_page({"type": "page", "url": "https://example.com/"}) is True


def test_is_real_page_rejects_missing_type():
    assert daemon._is_real_page({"url": "https://example.com/"}) is False


def test_is_real_page_rejects_non_page_types():
    assert daemon._is_real_page({"type": "iframe", "url": "https://example.com/"}) is False
    assert daemon._is_real_page({"type": "service_worker", "url": "https://example.com/"}) is False


def test_is_real_page_rejects_internal_urls():
    for url in ("chrome://newtab", "chrome-extension://abc", "about:blank", "devtools://xyz"):
        assert daemon._is_real_page({"type": "page", "url": url}) is False


def test_is_real_page_handles_missing_url():
    # Empty string url passes the prefix check; that's fine.
    assert daemon._is_real_page({"type": "page"}) is True


def test_resolve_ws_url_prefers_explicit_ws(monkeypatch):
    monkeypatch.setenv("VESTA_BROWSER_CDP_WS", "ws://custom/endpoint")
    monkeypatch.setenv("VESTA_BROWSER_CDP_PORT", "1234")
    assert daemon.resolve_ws_url() == "ws://custom/endpoint"


def test_resolve_ws_url_errors_when_nothing_set(monkeypatch):
    monkeypatch.delenv("VESTA_BROWSER_CDP_WS", raising=False)
    monkeypatch.delenv("VESTA_BROWSER_CDP_PORT", raising=False)
    with pytest.raises(RuntimeError, match="CDP_PORT or VESTA_BROWSER_CDP_WS"):
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


def test_fetch_user_agent_returns_none_without_env(monkeypatch):
    monkeypatch.delenv("VESTA_BROWSER_CDP_PORT", raising=False)
    assert daemon._fetch_user_agent() is None
