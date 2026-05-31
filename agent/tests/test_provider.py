"""Tests for the agent's provider-auth state. Mirror of the Rust tests in
vestad/src/providers/openrouter.rs — covers OpenRouter file format/shell-escaping,
provider-file parser (commented/partial/prefix-extended), Claude credentials auth
check (refresh-token-aware), and the boot/runtime state transitions."""

import json

import pytest

from core.provider import (
    ProviderAuthState,
    _check_claude_auth,
    _openrouter_provider_file,
    _openrouter_token_present,
    _provider_declares_openrouter,
    derive_status,
    observed_provider_failure,
    set_claude,
    set_openrouter,
)
from core.state_store import PersistedState, load_state


# --- OpenRouter file format ---


def test_openrouter_provider_file_format():
    f = _openrouter_provider_file("sk-or-v1-xyz", "anthropic/claude-sonnet-4-6")
    assert "export AGENT_PROVIDER=openrouter\n" in f
    assert "export AGENT_MODEL='anthropic/claude-sonnet-4-6'\n" in f
    assert "export ANTHROPIC_AUTH_TOKEN='sk-or-v1-xyz'\n" in f
    assert "export ANTHROPIC_API_KEY=\n" in f
    assert "export ANTHROPIC_SMALL_FAST_MODEL='anthropic/claude-haiku-4.5'\n" in f


def test_openrouter_provider_file_escapes_shell_metacharacters():
    injected = _openrouter_provider_file("k'; touch /tmp/pwned #", "m")
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


# --- State transitions (free functions) ---


@pytest.fixture
def prov(tmp_path, monkeypatch, config):
    # Redirect the module-level path constants into the tmp dir so we don't
    # touch the real ~/.claude during tests. Returns (config, persisted).
    from core import provider as provider_mod

    home = tmp_path / "home"
    monkeypatch.setattr(provider_mod, "CREDENTIALS_PATH", home / ".claude" / ".credentials.json")
    monkeypatch.setattr(provider_mod, "CLAUDE_JSON_PATH", home / ".claude.json")
    monkeypatch.setattr(provider_mod, "PROVIDER_ENV_PATH", home / ".claude" / "vesta-provider.env")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config, PersistedState()


def test_set_claude_writes_and_flips_state(prov):
    from core import provider as provider_mod

    config, persisted = prov
    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    status = set_claude(creds_json, config=config, persisted=persisted)
    assert status.state == ProviderAuthState.AUTHENTICATED
    assert status.kind == "claude"
    assert provider_mod.CREDENTIALS_PATH.read_text() == creds_json
    assert provider_mod.CLAUDE_JSON_PATH.read_text() == '{"hasCompletedOnboarding":true}'


def test_set_claude_clears_openrouter_provider_file(prov):
    from core import provider as provider_mod

    config, persisted = prov
    # Pre-existing OpenRouter file.
    provider_mod.PROVIDER_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    provider_mod.PROVIDER_ENV_PATH.write_text(_openrouter_provider_file("k", "m"))

    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    set_claude(creds_json, config=config, persisted=persisted)
    # Provider file should be empty so its exports don't override Claude creds at boot.
    assert provider_mod.PROVIDER_ENV_PATH.read_text() == ""


def test_set_openrouter_writes_and_flips_state(prov):
    from core import provider as provider_mod

    config, persisted = prov
    status = set_openrouter("sk-or-v1-x", "deepseek/deepseek-v4-flash", config=config, persisted=persisted)
    assert status.state == ProviderAuthState.AUTHENTICATED
    assert status.kind == "openrouter"
    assert status.model == "deepseek/deepseek-v4-flash"
    content = provider_mod.PROVIDER_ENV_PATH.read_text()
    assert "export AGENT_PROVIDER=openrouter\n" in content
    assert "export ANTHROPIC_AUTH_TOKEN='sk-or-v1-x'\n" in content


def test_observed_provider_failure_flips_state(prov):
    config, persisted = prov
    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    status = set_claude(creds_json, config=config, persisted=persisted)
    assert status.state == ProviderAuthState.AUTHENTICATED
    status = observed_provider_failure(status, config=config, persisted=persisted)
    assert status is not None and status.state == ProviderAuthState.NOT_AUTHENTICATED


def test_observed_provider_failure_flips_openrouter_on_402(prov):
    config, persisted = prov
    status = set_openrouter("sk-or-v1-key", "anthropic/claude-sonnet-4-6", config=config, persisted=persisted)
    assert status.state == ProviderAuthState.AUTHENTICATED
    # A 402 (insufficient credits) on the first model call flips an OpenRouter agent.
    status = observed_provider_failure(status, config=config, persisted=persisted)
    assert status is not None and status.state == ProviderAuthState.NOT_AUTHENTICATED


def test_observed_provider_failure_persists_across_restart(prov):
    config, persisted = prov
    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    status = set_claude(creds_json, config=config, persisted=persisted)
    observed_provider_failure(status, config=config, persisted=persisted)

    # Simulate restart: reload persisted state and re-derive.
    persisted2 = load_state(config)
    status2 = derive_status(config, persisted2)
    assert status2.state == ProviderAuthState.NOT_AUTHENTICATED


def test_boot_derives_authenticated_from_disk_when_no_persisted_state(prov):
    from core import provider as provider_mod

    config, persisted = prov
    # Pre-seed disk with valid Claude creds, no persisted auth state.
    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    provider_mod.CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    provider_mod.CREDENTIALS_PATH.write_text(creds_json)

    status = derive_status(config, persisted)
    assert status.state == ProviderAuthState.AUTHENTICATED
    assert status.kind == "claude"


def test_boot_with_no_credentials_at_all_is_not_authenticated(prov):
    config, persisted = prov
    status = derive_status(config, persisted)
    assert status.state == ProviderAuthState.NOT_AUTHENTICATED
    assert status.kind == "none"
