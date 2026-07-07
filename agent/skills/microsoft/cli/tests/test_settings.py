"""Locks the single-owner settings accessor: env-derived, read once per process."""

from microsoft_cli.settings import MicrosoftSettings, get_settings, DEFAULT_CLIENT_ID
from microsoft_cli.config import resolve_scopes, DEFAULT_CLIENT_SCOPES, OWNED_APP_SCOPES


def test_get_settings_reads_env_and_is_memoized(monkeypatch):
    monkeypatch.setenv("MICROSOFT_MCP_CLIENT_ID", "test-client-id")
    get_settings.cache_clear()

    first = get_settings()
    second = get_settings()

    assert isinstance(first, MicrosoftSettings)
    assert first.microsoft_mcp_client_id == "test-client-id"
    assert first is second

    get_settings.cache_clear()


def test_defaults_to_graph_cli_client_when_env_absent(monkeypatch):
    monkeypatch.delenv("MICROSOFT_MCP_CLIENT_ID", raising=False)
    get_settings.cache_clear()
    assert get_settings().microsoft_mcp_client_id == DEFAULT_CLIENT_ID
    get_settings.cache_clear()


def test_default_client_uses_dynamic_scopes(monkeypatch):
    monkeypatch.delenv("MICROSOFT_MCP_CLIENT_ID", raising=False)
    get_settings.cache_clear()
    assert resolve_scopes() == DEFAULT_CLIENT_SCOPES
    get_settings.cache_clear()


def test_custom_client_uses_default_scope(monkeypatch):
    monkeypatch.setenv("MICROSOFT_MCP_CLIENT_ID", "my-own-app")
    get_settings.cache_clear()
    assert resolve_scopes() == OWNED_APP_SCOPES
    get_settings.cache_clear()
