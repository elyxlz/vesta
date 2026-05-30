"""Tests for the agent's Provider class. Mirror of the deleted Rust tests in
vestad/src/agent_auth.rs — covers OpenRouter file format/shell-escaping,
provider-file parser (commented/partial/prefix-extended), and Claude credentials
auth check (refresh-token-aware)."""

import json

import pytest

from core.provider import (
    Provider,
    ProviderAuthState,
    _check_claude_auth,
    _openrouter_provider_file,
    _openrouter_token_present,
    _provider_declares_openrouter,
)
from core.state_store import PersistedState


# --- OpenRouter file format ---


def test_openrouter_provider_file_format():
    f = _openrouter_provider_file("sk-or-v1-xyz", "anthropic/claude-sonnet-4-6", zdr=True)
    assert "export AGENT_PROVIDER=openrouter\n" in f
    assert "export AGENT_MODEL='anthropic/claude-sonnet-4-6'\n" in f
    assert "export ANTHROPIC_AUTH_TOKEN='sk-or-v1-xyz'\n" in f
    assert "export ANTHROPIC_API_KEY=\n" in f
    assert "export ANTHROPIC_SMALL_FAST_MODEL='anthropic/claude-haiku-4.5'\n" in f
    assert "export OPENROUTER_ZDR=1\n" in f

    off = _openrouter_provider_file("k", "deepseek/deepseek-v4", zdr=False)
    assert "export OPENROUTER_ZDR=0\n" in off


def test_openrouter_provider_file_escapes_shell_metacharacters():
    injected = _openrouter_provider_file("k'; touch /tmp/pwned #", "m", zdr=True)
    assert "export ANTHROPIC_AUTH_TOKEN='k'\\''; touch /tmp/pwned #'" in injected
    assert "TOKEN=k';" not in injected


# --- Parser: provider-mode detection ---


def test_provider_declares_openrouter_happy_path():
    f = "export AGENT_PROVIDER=openrouter\nexport ANTHROPIC_AUTH_TOKEN='k'\n"
    assert _provider_declares_openrouter(f)
    assert _openrouter_token_present(f)


def test_provider_commented_line_rejected():
    f = "# export AGENT_PROVIDER=openrouter\nexport ANTHROPIC_AUTH_TOKEN='k'\n"
    assert not _provider_declares_openrouter(f)


def test_provider_prefix_extended_rejected():
    # AGENT_PROVIDER=openrouter_test must NOT match (exact-value compare).
    f = "export AGENT_PROVIDER=openrouter_test\nexport ANTHROPIC_AUTH_TOKEN='k'\n"
    assert not _provider_declares_openrouter(f)


def test_provider_empty_token_rejected():
    f = "export AGENT_PROVIDER=openrouter\nexport ANTHROPIC_AUTH_TOKEN=''\n"
    assert _provider_declares_openrouter(f)
    assert not _openrouter_token_present(f)


def test_provider_missing_token_rejected():
    f = "export AGENT_PROVIDER=openrouter\n"
    assert _provider_declares_openrouter(f)
    assert not _openrouter_token_present(f)


def test_provider_substring_only_rejected():
    # Legacy contains() check would have passed this; our line-parser must not.
    f = "# example: AGENT_PROVIDER=openrouter\n"
    assert not _provider_declares_openrouter(f)


# --- Claude credentials auth check ---


def test_claude_auth_valid_access_token():
    creds = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    assert _check_claude_auth(creds)


def test_claude_auth_expired_with_refresh_token_still_passes():
    # SDK auto-refreshes when a refresh token is present — count as authenticated.
    creds = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 0, "refreshToken": "r"}})
    assert _check_claude_auth(creds)


def test_claude_auth_expired_no_refresh_fails():
    creds = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 0}})
    assert not _check_claude_auth(creds)


def test_claude_auth_empty_refresh_token_doesnt_count():
    creds = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 0, "refreshToken": ""}})
    assert not _check_claude_auth(creds)


def test_claude_auth_malformed_json_fails():
    assert not _check_claude_auth("not json")
    assert not _check_claude_auth("{}")
    assert not _check_claude_auth(json.dumps({"claudeAiOauth": None}))


# --- Provider class transitions ---


@pytest.fixture
def provider(tmp_path, monkeypatch, config):
    # Redirect the module-level path constants into the tmp dir so we don't
    # touch the real ~/.claude during tests.
    from core import provider as provider_mod

    home = tmp_path / "home"
    monkeypatch.setattr(provider_mod, "CREDENTIALS_PATH", home / ".claude" / ".credentials.json")
    monkeypatch.setattr(provider_mod, "CLAUDE_JSON_PATH", home / ".claude.json")
    monkeypatch.setattr(provider_mod, "PROVIDER_ENV_PATH", home / ".claude" / "vesta-provider.env")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    persisted = PersistedState()
    return Provider(config, persisted)


def test_set_claude_writes_and_flips_state(provider):
    from core import provider as provider_mod

    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    provider.set_claude(creds_json)
    assert provider.status.state == ProviderAuthState.AUTHENTICATED
    assert provider.status.kind == "claude"
    assert provider_mod.CREDENTIALS_PATH.read_text() == creds_json
    assert provider_mod.CLAUDE_JSON_PATH.read_text() == '{"hasCompletedOnboarding":true}'


def test_set_claude_clears_openrouter_provider_file(provider):
    from core import provider as provider_mod

    # Pre-existing OpenRouter file.
    provider_mod.PROVIDER_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    provider_mod.PROVIDER_ENV_PATH.write_text(_openrouter_provider_file("k", "m", True))

    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    provider.set_claude(creds_json)
    # Provider file should be empty so its exports don't override Claude creds at boot.
    assert provider_mod.PROVIDER_ENV_PATH.read_text() == ""


def test_set_openrouter_writes_and_flips_state(provider):
    from core import provider as provider_mod

    provider.set_openrouter("sk-or-v1-x", "deepseek/deepseek-v4-flash", zdr=True)
    assert provider.status.state == ProviderAuthState.AUTHENTICATED
    assert provider.status.kind == "openrouter"
    assert provider.status.model == "deepseek/deepseek-v4-flash"
    content = provider_mod.PROVIDER_ENV_PATH.read_text()
    assert "export AGENT_PROVIDER=openrouter\n" in content
    assert "export ANTHROPIC_AUTH_TOKEN='sk-or-v1-x'\n" in content


def test_observed_401_flips_state(provider):
    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    provider.set_claude(creds_json)
    assert provider.status.state == ProviderAuthState.AUTHENTICATED
    provider.observed_401()
    assert provider.status.state == ProviderAuthState.NOT_AUTHENTICATED


def test_observed_401_persists_across_restart(tmp_path, monkeypatch, config):
    from core import provider as provider_mod

    home = tmp_path / "home"
    monkeypatch.setattr(provider_mod, "CREDENTIALS_PATH", home / ".claude" / ".credentials.json")
    monkeypatch.setattr(provider_mod, "CLAUDE_JSON_PATH", home / ".claude.json")
    monkeypatch.setattr(provider_mod, "PROVIDER_ENV_PATH", home / ".claude" / "vesta-provider.env")
    config.data_dir.mkdir(parents=True, exist_ok=True)

    persisted = PersistedState()
    p1 = Provider(config, persisted)
    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    p1.set_claude(creds_json)
    p1.observed_401()

    # Simulate restart by constructing a new Provider with reloaded persisted state.
    from core.state_store import load_state

    persisted2 = load_state(config)
    p2 = Provider(config, persisted2)
    assert p2.status.state == ProviderAuthState.NOT_AUTHENTICATED


def test_boot_derives_authenticated_from_disk_when_no_persisted_state(tmp_path, monkeypatch, config):
    from core import provider as provider_mod

    home = tmp_path / "home"
    monkeypatch.setattr(provider_mod, "CREDENTIALS_PATH", home / ".claude" / ".credentials.json")
    monkeypatch.setattr(provider_mod, "PROVIDER_ENV_PATH", home / ".claude" / "vesta-provider.env")
    monkeypatch.setattr(provider_mod, "CLAUDE_JSON_PATH", home / ".claude.json")
    config.data_dir.mkdir(parents=True, exist_ok=True)

    # Pre-seed disk with valid Claude creds, no persisted auth state.
    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    provider_mod.CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    provider_mod.CREDENTIALS_PATH.write_text(creds_json)

    persisted = PersistedState()
    p = Provider(config, persisted)
    assert p.status.state == ProviderAuthState.AUTHENTICATED
    assert p.status.kind == "claude"


def test_boot_with_no_credentials_at_all_is_not_authenticated(tmp_path, monkeypatch, config):
    from core import provider as provider_mod

    home = tmp_path / "home"
    monkeypatch.setattr(provider_mod, "CREDENTIALS_PATH", home / ".claude" / ".credentials.json")
    monkeypatch.setattr(provider_mod, "PROVIDER_ENV_PATH", home / ".claude" / "vesta-provider.env")
    monkeypatch.setattr(provider_mod, "CLAUDE_JSON_PATH", home / ".claude.json")
    config.data_dir.mkdir(parents=True, exist_ok=True)

    persisted = PersistedState()
    p = Provider(config, persisted)
    assert p.status.state == ProviderAuthState.NOT_AUTHENTICATED
    assert p.status.kind == "none"
