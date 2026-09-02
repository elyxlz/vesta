"""`auth.get_token` refreshes each account with the client that signed it in.

An MSAL refresh token is bound to the client id that minted it, while the cache lists accounts
independently of client id. One cache therefore holds an account signed in under the shared default
client next to an account signed in under an owned app registration (`MICROSOFT_MCP_CLIENT_ID=<app>
microsoft auth login`), and `acquire_token_silent` finds only the refresh tokens of the app's own
client. These tests run the real MSAL app over a serialized cache and pin that each account is
refreshed through an app built for the client holding its refresh token, with that client's scopes.
"""

from __future__ import annotations

import json
import pathlib as pl

import pytest
from microsoft_cli import auth
from microsoft_cli.config import DEFAULT_CLIENT_SCOPES, OWNED_APP_SCOPES
from microsoft_cli.settings import DEFAULT_CLIENT_ID, OWA_REST_CLIENT_ID, get_settings

OWNED_APP = "11111111-2222-3333-4444-555555555555"
ENVIRONMENT = "login.microsoftonline.com"
USER_ACCOUNT = "user-oid.tenant"
AGENT_ACCOUNT = "agent-oid.tenant"


def _account(home_account_id: str, username: str) -> dict[str, str]:
    return {
        "home_account_id": home_account_id,
        "environment": ENVIRONMENT,
        "realm": "tenant",
        "local_account_id": home_account_id.partition(".")[0],
        "username": username,
        "authority_type": "MSSTS",
    }


def _refresh_token(home_account_id: str, client_id: str) -> dict[str, str]:
    return {
        "credential_type": "RefreshToken",
        "secret": f"rt-{client_id}",
        "home_account_id": home_account_id,
        "environment": ENVIRONMENT,
        "client_id": client_id,
        "target": "openid profile offline_access",
    }


def _write_cache(cache_file: pl.Path, *, accounts: list[dict[str, str]], refresh_tokens: list[dict[str, str]]) -> None:
    state = {
        "Account": {f"account-{i}": account for i, account in enumerate(accounts)},
        "RefreshToken": {f"rt-{i}": rt for i, rt in enumerate(refresh_tokens)},
    }
    cache_file.write_text(json.dumps(state))


@pytest.fixture
def minted(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, list[str], str]]:
    """Replace the network refresh with a recorder: (client id, scopes, account) per mint, token = client id."""
    calls: list[tuple[str, list[str], str]] = []

    def fake_acquire_token_silent(self: auth.msal.PublicClientApplication, scopes: list[str], account: dict[str, str]) -> dict[str, str]:
        calls.append((self.client_id, scopes, account["home_account_id"]))
        return {"access_token": self.client_id}

    monkeypatch.setattr(auth.msal.PublicClientApplication, "acquire_token_silent", fake_acquire_token_silent)
    monkeypatch.delenv("MICROSOFT_MCP_CLIENT_ID", raising=False)
    get_settings.cache_clear()
    yield calls
    get_settings.cache_clear()


def test_each_account_mints_with_the_client_that_signed_it_in(minted: list[tuple[str, list[str], str]], tmp_path: pl.Path) -> None:
    cache_file = tmp_path / "auth_cache.bin"
    _write_cache(
        cache_file,
        accounts=[_account(USER_ACCOUNT, "user@example.org"), _account(AGENT_ACCOUNT, "agent@example.org")],
        refresh_tokens=[_refresh_token(USER_ACCOUNT, DEFAULT_CLIENT_ID), _refresh_token(AGENT_ACCOUNT, OWNED_APP)],
    )

    assert auth.get_token(cache_file, DEFAULT_CLIENT_SCOPES, account_id=USER_ACCOUNT) == DEFAULT_CLIENT_ID
    assert auth.get_token(cache_file, DEFAULT_CLIENT_SCOPES, account_id=AGENT_ACCOUNT) == OWNED_APP

    assert minted == [
        (DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SCOPES, USER_ACCOUNT),
        (OWNED_APP, OWNED_APP_SCOPES, AGENT_ACCOUNT),
    ]


@pytest.mark.parametrize(
    ("refresh_token_clients", "expected_client"),
    [
        ([OWNED_APP, DEFAULT_CLIENT_ID], DEFAULT_CLIENT_ID),
        ([OWA_REST_CLIENT_ID], DEFAULT_CLIENT_ID),
        ([OWA_REST_CLIENT_ID, OWNED_APP], OWNED_APP),
    ],
)
def test_the_configured_client_wins_and_owa_rest_tokens_are_not_graph_candidates(
    minted: list[tuple[str, list[str], str]], tmp_path: pl.Path, refresh_token_clients: list[str], expected_client: str
) -> None:
    cache_file = tmp_path / "auth_cache.bin"
    _write_cache(
        cache_file,
        accounts=[_account(USER_ACCOUNT, "user@example.org")],
        refresh_tokens=[_refresh_token(USER_ACCOUNT, client_id) for client_id in refresh_token_clients],
    )

    assert auth.get_token(cache_file, DEFAULT_CLIENT_SCOPES, account_id=USER_ACCOUNT) == expected_client
    assert [client_id for client_id, _scopes, _account in minted] == [expected_client]
