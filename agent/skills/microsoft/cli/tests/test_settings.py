"""Locks the single-owner settings accessor: env-derived, read once per process."""

from microsoft_cli.settings import MicrosoftSettings, get_settings


def test_get_settings_reads_env_and_is_memoized(monkeypatch):
    monkeypatch.setenv("MICROSOFT_MCP_CLIENT_ID", "test-client-id")
    get_settings.cache_clear()

    first = get_settings()
    second = get_settings()

    assert isinstance(first, MicrosoftSettings)
    assert first.microsoft_mcp_client_id == "test-client-id"
    assert first is second

    get_settings.cache_clear()
