"""vestad_client.send_user_notification is best-effort: it no-ops when the agent identity is missing
and swallows a transport failure, so raising a user-facing notification can never disrupt the turn that
emitted it. The happy-path wire contract (URL, X-Agent-Token, JSON body) is exercised by the Docker
integration suite."""

import socket

import pytest

from core import vestad_client


def _closed_port() -> int:
    """A port that is bound then released, so a connect to it refuses fast (deterministic, hermetic)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.anyio
async def test_send_user_notification_is_a_noop_without_agent_identity(monkeypatch):
    for var in ("VESTAD_PORT", "AGENT_NAME", "AGENT_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    # Returns without raising and without attempting any request.
    assert await vestad_client.send_user_notification("message", "scout", "hi") is None


@pytest.mark.anyio
async def test_send_user_notification_swallows_an_unreachable_vestad(monkeypatch):
    monkeypatch.setenv("VESTAD_PORT", str(_closed_port()))
    monkeypatch.setenv("AGENT_NAME", "scout")
    monkeypatch.setenv("AGENT_TOKEN", "tok")
    # vestad is not listening: the connection failure is logged and swallowed, never raised.
    assert await vestad_client.send_user_notification("rate_limited", "scout", "usage limit reached") is None
