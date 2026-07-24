"""account_profile() backfills the IMAP/SMTP host for a hostless profile.

When an account is saved under the ``generic`` provider (which has no host
defaults) but its email address is on a domain we recognise, the resolved
profile should borrow just the host/port from the detected provider so an
app-password account on e.g. Gmail works without hand-editing ``imap_host``.
The auth strategy and stored credentials must be left untouched, unknown
domains must not be inferred, and an explicit per-account host must still win.

imap_client imports imap_tools (from the on-box runtime); we stub it so the
module imports without the venv.
"""

import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def _install_imap_tools_stub():
    if "imap_tools" not in sys.modules:
        it = types.ModuleType("imap_tools")

        def _and(*_a, **_k):
            return None

        class MailBox:
            def __init__(self, *_a, **_k):
                pass

        class MailMessageFlags:
            DRAFT = "\\Draft"
            SEEN = "\\Seen"
            ANSWERED = "\\Answered"

        it.AND = _and
        it.MailBox = MailBox
        it.MailMessageFlags = MailMessageFlags
        sys.modules["imap_tools"] = it


_install_imap_tools_stub()
import imap_client


def _patch(monkeypatch, cfg, tok=None):
    monkeypatch.setattr(imap_client, "load_config", lambda _a: cfg)
    monkeypatch.setattr(imap_client, "load_token", lambda _a: tok)


def test_generic_known_domain_infers_host(monkeypatch):
    _patch(monkeypatch, {"user": "someone@gmail.com", "provider": "generic"})
    name, profile = imap_client.account_profile("x")
    assert name == "generic"
    assert profile.get("imap_host") == "imap.gmail.com"
    assert profile.get("smtp_host") == "smtp.gmail.com"
    # The generic provider authenticates with an app password; inference must
    # not switch that to OAuth.
    assert profile.get("auth_strategy") == "app-password"


def test_generic_unknown_domain_stays_hostless(monkeypatch):
    _patch(monkeypatch, {"user": "me@my-corp-vanity.example", "provider": "generic"})
    _name, profile = imap_client.account_profile("y")
    assert not profile.get("imap_host")


def test_explicit_config_host_wins(monkeypatch):
    _patch(
        monkeypatch,
        {
            "user": "someone@gmail.com",
            "provider": "generic",
            "imap_host": "imap.custom.example",
        },
    )
    _name, profile = imap_client.account_profile("z")
    assert profile.get("imap_host") == "imap.custom.example"
