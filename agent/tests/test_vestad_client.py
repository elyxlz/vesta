"""vestad_client calls are best-effort: they no-op or return None when the agent identity is missing
or vestad is unreachable, so talking to vestad can never disrupt the turn that asked. The happy-path
wire contract (URL, X-Agent-Token, JSON body) is exercised by the Docker integration suite."""

import socket
from unittest.mock import AsyncMock, patch

import pytest

from core import lifecycle, vestad_client


def _closed_port() -> int:
    """A port that is bound then released, so a connect to it refuses fast (deterministic, hermetic)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("args", "expected"),
    [((), lifecycle.AGENT_RESTART), ((lifecycle.COMPACTION_RESTART,), lifecycle.COMPACTION_RESTART)],
    ids=["defaults to the canonical agent reason", "forwards a specific reason"],
)
async def test_restart_carries_a_reason(args, expected):
    with patch("core.vestad_client._request_lifecycle", new_callable=AsyncMock, return_value=True) as request:
        assert await vestad_client.request_restart(*args)

    request.assert_awaited_once_with("restart", reason=expected)


@pytest.mark.anyio
async def test_fetch_user_devices_is_none_without_identity_or_vestad(monkeypatch):
    for var in ("BOX_HOST", "VESTAD_PORT", "AGENT_NAME", "AGENT_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    assert await vestad_client.fetch_user_devices() is None
    monkeypatch.setenv("BOX_HOST", "127.0.0.1")
    monkeypatch.setenv("VESTAD_PORT", str(_closed_port()))
    monkeypatch.setenv("AGENT_NAME", "scout")
    monkeypatch.setenv("AGENT_TOKEN", "tok")
    # vestad is not listening: None, never an exception, so the tool reports it instead of crashing.
    assert await vestad_client.fetch_user_devices() is None
