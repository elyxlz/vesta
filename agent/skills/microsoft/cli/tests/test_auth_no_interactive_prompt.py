"""`auth.get_token` must never start an interactive sign-in.

A data command (`email list`, `calendar list`, the notification daemon's poll) resolves its Graph
token through `auth.get_token`. If that helper falls back to a device flow when the cache holds
nothing usable, three things go wrong at once on an account that reaches its mailbox over the OWA
REST path: the command blocks for the ~15 minute lifetime of a device code, it prints a live code
nobody asked for, and the eventual "device code has expired" error is not a permission failure, so
`backend.run(AUTO, ...)` re-raises it instead of falling through to the backend that does work.

The contract these tests pin: no cached token means `GraphUnavailableError`, which is exactly what
`backend.run` treats as "Graph is unavailable, use OWA REST".
"""

from __future__ import annotations

import pathlib as pl
from unittest.mock import MagicMock

import pytest
from microsoft_cli import auth, backend


def _app(*, accounts: list[dict], silent_result: dict | None) -> MagicMock:
    app = MagicMock()
    app.get_accounts.return_value = accounts
    app.acquire_token_silent.return_value = silent_result
    app.token_cache = None
    return app


def test_no_cached_token_raises_graph_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: pl.Path) -> None:
    app = _app(accounts=[{"home_account_id": "abc", "username": "a@example.org"}], silent_result=None)
    monkeypatch.setattr(auth, "get_app", lambda *a, **k: app)
    device_flow = MagicMock()
    monkeypatch.setattr(auth, "_run_device_flow", device_flow)

    with pytest.raises(backend.GraphUnavailableError):
        auth.get_token(tmp_path / "cache.json", ["Mail.Read"])

    device_flow.assert_not_called()


def test_no_account_at_all_raises_graph_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: pl.Path) -> None:
    app = _app(accounts=[], silent_result=None)
    monkeypatch.setattr(auth, "get_app", lambda *a, **k: app)
    device_flow = MagicMock()
    monkeypatch.setattr(auth, "_run_device_flow", device_flow)

    with pytest.raises(backend.GraphUnavailableError):
        auth.get_token(tmp_path / "cache.json", ["Mail.Read"])

    device_flow.assert_not_called()


def test_cached_token_is_still_returned(monkeypatch: pytest.MonkeyPatch, tmp_path: pl.Path) -> None:
    app = _app(
        accounts=[{"home_account_id": "abc", "username": "a@example.org"}],
        silent_result={"access_token": "tok"},
    )
    monkeypatch.setattr(auth, "get_app", lambda *a, **k: app)

    assert auth.get_token(tmp_path / "cache.json", ["Mail.Read"]) == "tok"


def test_auto_backend_falls_through_to_owa_when_graph_has_no_token(monkeypatch: pytest.MonkeyPatch, tmp_path: pl.Path) -> None:
    """The end-to-end point of the fix: the dispatcher reaches the working backend."""
    app = _app(accounts=[], silent_result=None)
    monkeypatch.setattr(auth, "get_app", lambda *a, **k: app)

    def graph_fn() -> str:
        auth.get_token(tmp_path / "cache.json", ["Mail.Read"])
        return "graph-result"

    assert backend.run(backend.AUTO, graph_fn, lambda: "owa-result") == "owa-result"
