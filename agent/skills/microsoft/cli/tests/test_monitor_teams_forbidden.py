"""A Teams 403 is an authorization verdict, so the monitor self-heals instead of erroring forever.

A tenant can grant the Teams *scope string* at device-flow sign-in (so `auth setup` marks the
account Teams-capable) while still forbidding the actual Teams Graph calls. Without self-heal the
monitor logs an error every poll cycle indefinitely. `_poll_teams_account` therefore unmarks the
account on a 403 (stops polling a blocked endpoint) but leaves the marker intact on a transient
error (e.g. a 503), so a real Teams account is not disabled by a blip.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
from microsoft_cli import monitor, teams
from microsoft_cli.config import Config


class _Ctx:
    def __init__(self) -> None:
        self.monitor_logger = logging.getLogger("test-monitor-teams")
        self.http_client = None  # never used: _my_id is monkeypatched below


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://graph.microsoft.com/v1.0/me")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"{status}", request=request, response=response)


def test_forbidden_unmarks_the_account(tmp_path, monkeypatch) -> None:
    cfg = Config(data_dir=tmp_path)
    teams.mark_device_account("user@example.com", cfg)
    assert "user@example.com" in teams.list_accounts(cfg)

    monkeypatch.setattr(teams, "resolve_token", lambda _cfg, _email: "tok")
    monkeypatch.setattr(teams, "_my_id", lambda _client, _tok: (_ for _ in ()).throw(_http_error(403)))

    ok = monitor._poll_teams_account(_Ctx(), cfg, "user@example.com", datetime.now(UTC), False)

    assert ok is False
    assert teams.list_accounts(cfg) == []  # unmarked: monitor stops polling a blocked endpoint next cycle


def test_transient_error_keeps_the_marker(tmp_path, monkeypatch) -> None:
    cfg = Config(data_dir=tmp_path)
    teams.mark_device_account("user@example.com", cfg)

    monkeypatch.setattr(teams, "resolve_token", lambda _cfg, _email: "tok")
    monkeypatch.setattr(teams, "_my_id", lambda _client, _tok: (_ for _ in ()).throw(_http_error(503)))

    ok = monitor._poll_teams_account(_Ctx(), cfg, "user@example.com", datetime.now(UTC), False)

    assert ok is False
    assert "user@example.com" in teams.list_accounts(cfg)  # a blip must not disable a real Teams account


def test_is_forbidden_helper() -> None:
    assert monitor._is_forbidden(_http_error(403)) is True
    assert monitor._is_forbidden(_http_error(503)) is False
    assert monitor._is_forbidden(RuntimeError("no response attr")) is False
