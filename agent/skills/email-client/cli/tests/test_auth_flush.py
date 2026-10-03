"""The interactive auth flows must flush their URL and code before blocking.

With stdout redirected to a file or pipe, Python block-buffers it, so an
unflushed code stays invisible to whoever tails the log until the process exits.
"""

import io
import sys
import types

import pytest
from email_client import auth


class _StopError(Exception):
    pass


def _block_buffered_stdout(monkeypatch) -> io.BytesIO:
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="utf-8", line_buffering=False))
    return raw


def test_device_flow_code_is_visible_while_polling(monkeypatch):
    raw = _block_buffered_stdout(monkeypatch)
    seen: list[str] = []

    class _App:
        def __init__(self, *_a, **_kw):
            pass

        def initiate_device_flow(self, scopes):
            return {"user_code": "ABCD-1234", "verification_uri": "https://example.test/device"}

        def acquire_token_by_device_flow(self, flow):
            seen.append(raw.getvalue().decode())
            raise _StopError

    monkeypatch.setitem(sys.modules, "msal", types.SimpleNamespace(PublicClientApplication=_App))
    profile = {"oauth_client_id": "cid", "oauth_authority": "https://example.test", "oauth_scopes": ["s"]}
    with pytest.raises(_StopError):
        auth.auth_device_flow("microsoft-work", profile, "user@example.test")
    assert "ABCD-1234" in seen[0]
    assert "https://example.test/device" in seen[0]


def test_loopback_consent_url_is_visible_while_waiting(monkeypatch):
    raw = _block_buffered_stdout(monkeypatch)
    seen: list[str] = []

    def _sleep(_s):
        seen.append(raw.getvalue().decode())
        raise _StopError

    monkeypatch.setattr(auth.time, "sleep", _sleep)
    monkeypatch.setattr(auth._RedirectHandler, "captured", None)
    profile = {
        "oauth_client_id": "cid",
        "oauth_scopes": ["s"],
        "oauth_auth_url": "https://example.test/auth",
    }
    with pytest.raises(_StopError):
        auth.auth_loopback_oauth("gmail", profile, "user@example.test")
    assert "https://example.test/auth?" in seen[0]
