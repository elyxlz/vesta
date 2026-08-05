"""`auth setup` scope selection for personal (MSA) vs work/school accounts.

Teams Graph permissions are work/school only. The consumer token endpoint answers a request that
includes them with a *narrowed* grant (openid profile) rather than an error, so the request scopes
must exclude Teams for a personal account, and the granted scopes, not the requested ones, must
decide whether an account is marked Teams-capable.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from microsoft_cli import auth_commands, teams
from microsoft_cli.config import DEFAULT_CLIENT_SCOPES, Config

TEAMS_GRANT = "https://graph.microsoft.com/Chat.ReadWrite https://graph.microsoft.com/Team.ReadBasic.All openid profile"
MAIL_GRANT = "https://graph.microsoft.com/Mail.ReadWrite https://graph.microsoft.com/Calendars.ReadWrite openid profile"
NARROWED_GRANT = "openid profile"


@pytest.mark.parametrize("email", ["a@hotmail.com", "a@outlook.com", "a@live.com", "a@msn.com", "a@hotmail.co.uk", "a@outlook.fr"])
def test_personal_account_never_requests_teams_scopes(email: str) -> None:
    scopes = auth_commands.setup_scopes_for(email)
    assert scopes == list(DEFAULT_CLIENT_SCOPES)
    assert not [s for s in scopes if s in teams.TEAMS_SCOPES]


@pytest.mark.parametrize("email", ["a@contoso.com", "a@example.org"])
def test_work_account_still_bundles_teams_scopes(email: str) -> None:
    scopes = auth_commands.setup_scopes_for(email)
    for scope in teams.TEAMS_SCOPES:
        assert scope in scopes
    for scope in DEFAULT_CLIENT_SCOPES:
        assert scope in scopes


@pytest.mark.parametrize(
    ("granted", "expected"),
    [(TEAMS_GRANT, True), (MAIL_GRANT, False), (NARROWED_GRANT, False), ("", False)],
)
def test_granted_teams_scope_reads_the_grant_not_the_request(granted: str, expected: bool) -> None:
    assert auth_commands.granted_teams_scope({"scope": granted}) is expected
    assert auth_commands.granted_teams_scope({}) is False


def _patch_device_flow(monkeypatch: pytest.MonkeyPatch, result: dict) -> list[str]:
    """Wire a fake MSAL app whose device flow returns `result`; collect marked Teams accounts."""
    app = MagicMock()
    app.acquire_token_by_device_flow.return_value = result
    app.token_cache = SimpleNamespace()
    app.get_accounts.return_value = []
    monkeypatch.setattr(auth_commands.auth, "get_app", lambda *a, **k: app)
    marked: list[str] = []
    monkeypatch.setattr(teams, "mark_device_account", lambda email, config: marked.append(email))
    return marked


def test_setup_does_not_claim_teams_when_the_grant_was_narrowed(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    config = Config(data_dir=tmp_path)
    teams.mark_device_account("a@hotmail.com", config)  # stale marker left by a setup that trusted the request scopes
    marked = _patch_device_flow(monkeypatch, {"access_token": "t", "scope": NARROWED_GRANT})
    out = auth_commands._setup_finish_device(config, account_email="a@hotmail.com", flow_cache="{}")
    assert out["status"] == "success"
    assert out["provisioned"] == "mail/calendar"
    assert "Teams over Graph is not available" in out["message"]
    assert marked == []
    # The stale device marker is gone, so has_token stops claiming Teams for this account.
    assert teams.list_accounts(config) == []


def test_setup_still_provisions_teams_when_the_grant_includes_it(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    marked = _patch_device_flow(monkeypatch, {"access_token": "t", "scope": TEAMS_GRANT})
    out = auth_commands._setup_finish_device(Config(data_dir=tmp_path), account_email="a@contoso.com", flow_cache="{}")
    assert out["provisioned"] == "mail/calendar, Teams"
    assert marked == ["a@contoso.com"]


def test_teams_complete_reports_the_real_reason_instead_of_marking_the_account(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    result = {"access_token": "t", "scope": NARROWED_GRANT, "id_token_claims": {"preferred_username": "a@hotmail.com"}}
    marked = _patch_device_flow(monkeypatch, result)
    out = auth_commands.teams_complete(Config(data_dir=tmp_path), flow_cache="{}")
    # An answer about the account, not a command failure: the sign-in itself succeeded.
    assert out["status"] == "teams_unavailable"
    assert "work/school only" in out["message"]
    assert marked == []
