"""`email reply` refuses when the reply would go only to a no-reply address (it bounces)."""

from types import SimpleNamespace

import pytest
from microsoft_cli import backend, cli
from microsoft_cli.config import Config


def _addr(address):
    return {"emailAddress": {"address": address}}


def _args(**over):
    base = {
        "command": "reply",
        "account": "me@example.com",
        "email_id": "m1",
        "body": "Thanks",
        "attachments": None,
        "reply_all": False,
        "html": False,
        "allow_noreply": False,
        "backend": backend.GRAPH,
    }
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture
def graph(monkeypatch):
    """Fake Graph: `source` is what GET /me/messages/{id} returns; `calls` records lookups and replies."""
    state = {"source": {}, "calls": []}
    monkeypatch.setattr(cli.email.auth, "get_account_id_by_email", lambda *_a: "acct-1")

    def request(_config, _client, method, path, _account_id, **kwargs):
        state["calls"].append((method, path, kwargs["params"] if "params" in kwargs else None))
        return state["source"]

    monkeypatch.setattr(cli.email.graph, "request_cfg", request)
    monkeypatch.setattr(cli.email, "reply_to_email", lambda _c, _cl, **kw: state["calls"].append(("reply", kw["email_id"], None)) or "sent")
    return state


@pytest.mark.parametrize(
    "address",
    [
        "noreply@example.org",
        "no-reply@example.com",
        "No_Reply@example.com",
        "DoNotReply@example.com",
        "do-not-reply@example.com",
        "messages-noreply@example.com",
        "noreply-iam@example.com",
    ],
)
def test_reply_to_noreply_sender_is_refused(graph, address):
    graph["source"] = {"from": _addr(address), "replyTo": []}

    with pytest.raises(ValueError, match="no-reply address") as err:
        cli._dispatch_email(_args(), Config(), client=None)

    assert address in str(err.value)
    assert "--allow-noreply" in str(err.value)
    assert graph["calls"] == [("GET", "/me/messages/m1", {"$select": "from,replyTo"})]


def test_real_reply_to_overrides_noreply_from(graph):
    graph["source"] = {"from": _addr("noreply@example.com"), "replyTo": [_addr("host@example.com")]}

    assert cli._dispatch_email(_args(), Config(), client=None) == "sent"
    assert graph["calls"][-1] == ("reply", "m1", None)


def test_noreply_reply_to_is_refused_even_with_real_from(graph):
    graph["source"] = {"from": _addr("person@example.com"), "replyTo": [_addr("no-reply@example.com")]}

    with pytest.raises(ValueError, match=r"no-reply@example\.com"):
        cli._dispatch_email(_args(), Config(), client=None)


def test_real_sender_is_not_refused(graph):
    graph["source"] = {"from": _addr("person@example.com"), "replyTo": []}

    assert cli._dispatch_email(_args(), Config(), client=None) == "sent"


def test_allow_noreply_skips_the_check(graph):
    graph["source"] = {"from": _addr("noreply@example.com"), "replyTo": []}

    assert cli._dispatch_email(_args(allow_noreply=True), Config(), client=None) == "sent"
    assert graph["calls"] == [("reply", "m1", None)]


def test_reply_all_skips_the_check(graph):
    graph["source"] = {"from": _addr("noreply@example.com"), "replyTo": []}

    assert cli._dispatch_email(_args(reply_all=True), Config(), client=None) == "sent"
    assert graph["calls"] == [("reply", "m1", None)]


def test_owa_rest_backend_is_guarded_too(monkeypatch):
    monkeypatch.setattr(cli.owa_rest, "get_reply_source", lambda *_a, **_k: {"from": _addr("noreply@example.com"), "replyTo": []})
    monkeypatch.setattr(cli.owa_rest_commands, "reply_to_email", lambda *_a, **_k: "sent")

    with pytest.raises(ValueError, match="no-reply address"):
        cli._dispatch_email(_args(backend=backend.OWA_REST), Config(), client=None)


def test_allow_noreply_flag_parses():
    args = cli.build_parser().parse_args(["email", "reply", "--account", "me@example.com", "--id", "m1", "--body", "hi", "--allow-noreply"])
    assert args.allow_noreply is True
