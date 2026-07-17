"""Unit tests for the Teams-over-Graph backend.

Covers token markers (device + browser), token resolution and GraphUnavailableError fallback signalling,
the Graph transport shaping (chats/messages/send/start/channels/presence), the CLI dispatcher's
two-source routing via backend.run, and the monitor's new-chat notification emit.
"""

from __future__ import annotations

import base64
import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from microsoft_cli import backend, teams
from microsoft_cli.config import Config


def _make_token(exp: float) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


def _http_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://graph.microsoft.com/v1.0/me/chats")
    resp = httpx.Response(status, request=req)
    return httpx.HTTPStatusError("err", request=req, response=resp)


def _mock_client(json_response, status: int = 200) -> httpx.Client:
    mock = MagicMock(spec=httpx.Client)
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = b"{}"
    resp.json.return_value = json_response
    resp.raise_for_status = MagicMock()
    mock.get.return_value = resp
    mock.post.return_value = resp
    return mock


# ---------------------------------------------------------------------------
# Token markers
# ---------------------------------------------------------------------------


def test_has_token_false_when_no_file(tmp_path):
    assert teams.has_token("user@example.com", Config(data_dir=tmp_path)) is False


def test_has_token_true_for_fresh_browser_token(tmp_path):
    cfg = Config(data_dir=tmp_path)
    future = time.time() + 7200
    teams.save_token("user@example.com", cfg, token=_make_token(future), expires_at=future)
    assert teams.has_token("user@example.com", cfg) is True


def test_has_token_false_for_expired_browser_token(tmp_path):
    cfg = Config(data_dir=tmp_path)
    past = time.time() - 3600
    teams.save_token("user@example.com", cfg, token=_make_token(past), expires_at=past)
    assert teams.has_token("user@example.com", cfg) is False


def test_has_token_device_checks_msal_cache(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path)
    teams.mark_device_account("user@example.com", cfg)
    monkeypatch.setattr(teams.auth, "account_in_cache", lambda *a, **k: True)
    assert teams.has_token("user@example.com", cfg) is True
    monkeypatch.setattr(teams.auth, "account_in_cache", lambda *a, **k: False)
    assert teams.has_token("user@example.com", cfg) is False


def test_list_accounts_enumerates_markers(tmp_path):
    cfg = Config(data_dir=tmp_path)
    teams.save_token("a@x.com", cfg, token="t", expires_at=time.time() + 3600)
    teams.mark_device_account("b@y.com", cfg)
    assert teams.list_accounts(cfg) == ["a@x.com", "b@y.com"]


def test_list_accounts_empty_when_none(tmp_path):
    assert teams.list_accounts(Config(data_dir=tmp_path)) == []


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------


def test_graph_token_raises_graph_unavailable_when_account_unknown(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path)

    def _raise(*a, **k):
        raise ValueError("no account")

    monkeypatch.setattr(teams.auth, "get_account_id_by_email", _raise)
    with pytest.raises(backend.GraphUnavailableError):
        teams.graph_token(cfg, "user@example.com")


def test_graph_token_raises_graph_unavailable_when_no_silent_token(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path)
    monkeypatch.setattr(teams.auth, "get_account_id_by_email", lambda *a, **k: "acct-1")
    monkeypatch.setattr(teams.auth, "get_token_silent", lambda *a, **k: None)
    with pytest.raises(backend.GraphUnavailableError):
        teams.graph_token(cfg, "user@example.com")


def test_graph_token_returns_msal_token(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path)
    monkeypatch.setattr(teams.auth, "get_account_id_by_email", lambda *a, **k: "acct-1")
    monkeypatch.setattr(teams.auth, "get_token_silent", lambda *a, **k: "fresh")
    assert teams.graph_token(cfg, "user@example.com") == "fresh"


def test_captured_token_returns_browser_token(tmp_path):
    cfg = Config(data_dir=tmp_path)
    future = time.time() + 7200
    teams.save_token("user@example.com", cfg, token="cap-tok", expires_at=future)
    assert teams.captured_token(cfg, "user@example.com") == "cap-tok"


def test_captured_token_raises_when_missing(tmp_path):
    with pytest.raises(teams.TeamsNoTokenError, match="teams-capture"):
        teams.captured_token(Config(data_dir=tmp_path), "user@example.com")


def test_captured_token_raises_when_device_source(tmp_path):
    cfg = Config(data_dir=tmp_path)
    teams.mark_device_account("user@example.com", cfg)
    with pytest.raises(teams.TeamsNoTokenError):
        teams.captured_token(cfg, "user@example.com")


def test_resolve_token_prefers_device(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path)
    teams.mark_device_account("user@example.com", cfg)
    monkeypatch.setattr(teams, "graph_token", lambda *a, **k: "device-tok")
    assert teams.resolve_token(cfg, "user@example.com") == "device-tok"


def test_teams_no_token_is_runtime_error():
    assert isinstance(teams.TeamsNoTokenError("x"), RuntimeError)


# ---------------------------------------------------------------------------
# Transport shaping
# ---------------------------------------------------------------------------


def test_list_chats_uses_expand_orderby_and_top():
    client = _mock_client({"value": [{"id": "c1"}]})
    result = teams.list_chats(client, "tok", limit=10)
    assert result == [{"id": "c1"}]
    params = client.get.call_args.kwargs["params"]
    assert params["$expand"] == "members,lastMessagePreview"
    assert params["$orderby"] == "lastMessagePreview/createdDateTime desc"
    assert params["$top"] == "10"
    assert client.get.call_args.args[0].endswith("/me/chats")


def test_list_chats_caps_top_at_50():
    client = _mock_client({"value": []})
    teams.list_chats(client, "tok", limit=500)
    assert client.get.call_args.kwargs["params"]["$top"] == "50"


def test_send_chat_message_posts_body():
    client = _mock_client({"id": "m1"})
    result = teams.send_chat_message(client, "tok", chat_id="c1", body="hi")
    assert result == {"status": "sent", "chat_id": "c1", "id": "m1"}
    url = client.post.call_args.args[0]
    body = client.post.call_args.kwargs["json"]
    assert url.endswith("/chats/c1/messages")
    assert body == {"body": {"contentType": "text", "content": "hi"}}


def test_send_chat_message_html():
    client = _mock_client({"id": "m1"})
    teams.send_chat_message(client, "tok", chat_id="c1", body="<b>hi</b>", html=True)
    assert client.post.call_args.kwargs["json"]["body"]["contentType"] == "html"


def test_start_chat_one_on_one_binds_both_members():
    client = MagicMock(spec=httpx.Client)
    get_resp = MagicMock(status_code=200, content=b"{}")
    get_resp.raise_for_status = MagicMock()
    get_resp.json.return_value = {"userPrincipalName": "me@x.com"}
    post_resp = MagicMock(status_code=201, content=b"{}")
    post_resp.raise_for_status = MagicMock()
    post_resp.json.return_value = {"id": "chat-1"}
    client.get.return_value = get_resp
    client.post.return_value = post_resp

    result = teams.start_chat(client, "tok", members=["bob@x.com"])
    assert result == {"status": "created", "id": "chat-1", "chat_type": "oneOnOne"}
    payload = client.post.call_args.kwargs["json"]
    assert payload["chatType"] == "oneOnOne"
    binds = [m["user@odata.bind"] for m in payload["members"]]
    assert any("me@x.com" in b for b in binds)
    assert any("bob@x.com" in b for b in binds)


def test_start_chat_group_sets_topic():
    client = MagicMock(spec=httpx.Client)
    get_resp = MagicMock(status_code=200, content=b"{}")
    get_resp.raise_for_status = MagicMock()
    get_resp.json.return_value = {"userPrincipalName": "me@x.com"}
    post_resp = MagicMock(status_code=201, content=b"{}")
    post_resp.raise_for_status = MagicMock()
    post_resp.json.return_value = {"id": "chat-2"}
    client.get.return_value = get_resp
    client.post.return_value = post_resp

    result = teams.start_chat(client, "tok", members=["a@x.com", "b@x.com"], topic="Project")
    assert result["chat_type"] == "group"
    assert client.post.call_args_list[0].kwargs["json"]["topic"] == "Project"


def test_list_channels_selects_fields():
    client = _mock_client({"value": [{"id": "ch1", "displayName": "General"}]})
    result = teams.list_channels(client, "tok", team_id="t1")
    assert result[0]["displayName"] == "General"
    assert client.get.call_args.args[0].endswith("/teams/t1/channels")


def test_reply_channel_message_targets_replies_endpoint():
    client = _mock_client({"id": "r1"})
    result = teams.reply_channel_message(client, "tok", team_id="t1", channel_id="c1", message_id="m1", body="ok")
    assert result == {"status": "replied", "id": "r1"}
    assert client.post.call_args.args[0].endswith("/teams/t1/channels/c1/messages/m1/replies")


def test_set_presence_rejects_unknown_availability():
    with pytest.raises(teams.TeamsError):
        teams.set_presence(_mock_client({}), "tok", availability="Vibing")


def test_set_presence_posts_to_user_scoped_endpoint():
    client = _mock_client({"id": "my-guid"})
    result = teams.set_presence(client, "tok", availability="Busy", expires="PT1H")
    assert result == {"status": "set", "availability": "Busy"}
    url = client.post.call_args.args[0]
    body = client.post.call_args.kwargs["json"]
    assert url.endswith("/users/my-guid/presence/setUserPreferredPresence")
    assert body == {"availability": "Busy", "activity": "Busy", "expirationDuration": "PT1H"}


def test_get_presence_reads_me_presence():
    client = _mock_client({"availability": "Available"})
    assert teams.get_presence(client, "tok") == {"availability": "Available"}
    assert client.get.call_args.args[0].endswith("/me/presence")


def test_get_raises_http_status_error_on_403():
    mock = MagicMock(spec=httpx.Client)
    resp = MagicMock(status_code=403)
    resp.raise_for_status.side_effect = _http_error(403)
    mock.get.return_value = resp
    with pytest.raises(httpx.HTTPStatusError):
        teams.list_chats(mock, "tok")


# ---------------------------------------------------------------------------
# CLI dispatcher: two-source routing
# ---------------------------------------------------------------------------


def _teams_args(choice, command="chats"):
    return SimpleNamespace(backend=choice, account="me@x.com", command=command, limit=20)


def test_dispatch_forced_graph_uses_graph_token(monkeypatch):
    from microsoft_cli import cli

    seen = {}
    monkeypatch.setattr(cli.teams, "graph_token", lambda cfg, acct: "GTOK")
    monkeypatch.setattr(cli.teams, "captured_token", lambda cfg, acct: pytest.fail("must not use captured"))
    monkeypatch.setattr(cli.teams, "list_chats", lambda c, t, limit: seen.setdefault("tok", t) or [])
    cli._dispatch_teams(_teams_args(backend.GRAPH), Config(), MagicMock())
    assert seen["tok"] == "GTOK"


def test_dispatch_forced_owa_rest_uses_captured_token(monkeypatch):
    from microsoft_cli import cli

    seen = {}
    monkeypatch.setattr(cli.teams, "graph_token", lambda cfg, acct: pytest.fail("must not use graph"))
    monkeypatch.setattr(cli.teams, "captured_token", lambda cfg, acct: "CTOK")
    monkeypatch.setattr(cli.teams, "list_chats", lambda c, t, limit: seen.setdefault("tok", t) or [])
    cli._dispatch_teams(_teams_args(backend.OWA_REST), Config(), MagicMock())
    assert seen["tok"] == "CTOK"


def test_dispatch_auto_falls_back_to_captured_when_graph_unavailable(monkeypatch):
    from microsoft_cli import cli

    seen = {}

    def _unavail(cfg, acct):
        raise backend.GraphUnavailableError("no teams token")

    monkeypatch.setattr(cli.teams, "graph_token", _unavail)
    monkeypatch.setattr(cli.teams, "captured_token", lambda cfg, acct: "CTOK")
    monkeypatch.setattr(cli.teams, "list_chats", lambda c, t, limit: seen.setdefault("tok", t) or [])
    cli._dispatch_teams(_teams_args(backend.AUTO), Config(), MagicMock())
    assert seen["tok"] == "CTOK"


# ---------------------------------------------------------------------------
# auth teams-capture (paste)
# ---------------------------------------------------------------------------


def test_teams_capture_paste_saves_token(tmp_path):
    from microsoft_cli import auth_commands

    cfg = Config(data_dir=tmp_path)
    fresh = _make_token(time.time() + 7200)
    result = auth_commands.teams_capture(cfg, account_email="user@example.com", token=fresh)
    assert result["status"] == "success"
    assert teams.captured_token(cfg, "user@example.com") == fresh


def test_teams_capture_paste_rejects_garbage(tmp_path):
    from microsoft_cli import auth_commands

    cfg = Config(data_dir=tmp_path)
    result = auth_commands.teams_capture(cfg, account_email="user@example.com", token="not-a-jwt")
    assert result["status"] == "error"
    assert teams.has_token("user@example.com", cfg) is False


# ---------------------------------------------------------------------------
# Locked-tenant device-flow pivot to browser capture
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error_msg",
    [
        "AADSTS65001: The user or administrator has not consented to use the application.",
        "AADSTS90094: Admin consent is required.",
        "This app requires admin approval before it can be used.",
    ],
)
def test_consent_wall_detected(error_msg):
    from microsoft_cli import auth_commands

    assert auth_commands._is_consent_wall(error_msg) is True


def test_non_consent_error_not_flagged():
    from microsoft_cli import auth_commands

    assert auth_commands._is_consent_wall("authorization_pending") is False


def test_teams_complete_returns_pivot_on_admin_wall(tmp_path, monkeypatch):
    from microsoft_cli import auth_commands

    cfg = Config(data_dir=tmp_path)
    fake_app = MagicMock()
    fake_app.acquire_token_by_device_flow.return_value = {"error": "access_denied", "error_description": "AADSTS65001: not consented"}
    monkeypatch.setattr(auth_commands.auth, "get_app", lambda *a, **k: fake_app)
    result = auth_commands.teams_complete(cfg, flow_cache=json.dumps({"device_code": "x"}))
    assert result["status"] == "admin_consent_required"
    assert "teams-capture" in result["message"]


def test_complete_authentication_returns_pivot_on_admin_wall(tmp_path, monkeypatch):
    from microsoft_cli import auth_commands

    cfg = Config(data_dir=tmp_path)
    fake_app = MagicMock()
    fake_app.acquire_token_by_device_flow.return_value = {"error": "access_denied", "error_description": "AADSTS90094 admin consent required"}
    monkeypatch.setattr(auth_commands.auth, "get_app", lambda *a, **k: fake_app)
    result = auth_commands.complete_authentication(cfg, flow_cache=json.dumps({"device_code": "x"}))
    assert result["status"] == "admin_consent_required"
    assert "owa-login" in result["message"]


# ---------------------------------------------------------------------------
# Monitor: new-chat notification emit
# ---------------------------------------------------------------------------


def _teams_ctx(tmp_path, monkeypatch, chats):
    import logging

    from microsoft_cli.context import MicrosoftContext

    monkeypatch.setattr(teams, "resolve_token", lambda cfg, acct: "tok")
    monkeypatch.setattr(teams, "_my_id", lambda client, token: "me-guid")
    monkeypatch.setattr(teams, "list_chats", lambda client, token, limit: chats)
    return MicrosoftContext(
        cache_file=tmp_path / "cache.bin",
        http_client=MagicMock(),
        log_dir=tmp_path,
        notif_dir=tmp_path / "notif",
        monitor_base_dir=tmp_path,
        monitor_state_file=tmp_path / "state.txt",
        monitor_log_file=tmp_path / "m.log",
        monitor_logger=logging.getLogger("test.teams.monitor"),
        monitor_stop_event=MagicMock(),
        scopes=[],
        base_url="",
        upload_chunk_size=1,
        folders={},
    )


def test_poll_teams_emits_for_new_incoming_message(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from microsoft_cli import monitor

    chats = [
        {
            "id": "chat-1",
            "topic": "Standup",
            "lastMessagePreview": {
                "createdDateTime": "2026-07-10T12:00:00Z",
                "from": {"user": {"id": "other-guid", "displayName": "Bob"}},
                "body": {"content": "<p>hello there</p>"},
            },
        }
    ]
    ctx = _teams_ctx(tmp_path, monkeypatch, chats)
    last_dt = datetime(2026, 7, 10, 11, 0, tzinfo=UTC)
    monitor._poll_teams_account(ctx, Config(data_dir=tmp_path), "me@x.com", last_dt, False)

    files = list((tmp_path / "notif").glob("*.json"))
    assert len(files) == 1
    notif = json.loads(files[0].read_text())
    assert notif["type"] == "teams"
    assert notif["sender"] == "Bob"
    assert notif["topic"] == "Standup"
    assert notif["chat_id"] == "chat-1"
    assert "hello there" in notif["preview"]


def test_poll_teams_skips_own_message(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from microsoft_cli import monitor

    chats = [
        {
            "id": "chat-1",
            "lastMessagePreview": {
                "createdDateTime": "2026-07-10T12:00:00Z",
                "from": {"user": {"id": "me-guid", "displayName": "Me"}},
                "body": {"content": "my own message"},
            },
        }
    ]
    ctx = _teams_ctx(tmp_path, monkeypatch, chats)
    last_dt = datetime(2026, 7, 10, 11, 0, tzinfo=UTC)
    monitor._poll_teams_account(ctx, Config(data_dir=tmp_path), "me@x.com", last_dt, False)
    assert list((tmp_path / "notif").glob("*.json")) == []


# ---------------------------------------------------------------------------
# Monitor: Teams CHANNEL message notification emit + graceful degrade
# ---------------------------------------------------------------------------


def _teams_channels_ctx(tmp_path, monkeypatch, *, teams_list, channels=None, messages=None, list_teams_exc=None):
    """Wire a MicrosoftContext with the channel Graph calls mocked. Pass list_teams_exc to make
    team enumeration raise (the graceful-degrade path)."""
    import logging

    from microsoft_cli.context import MicrosoftContext

    monkeypatch.setattr(teams, "resolve_token", lambda cfg, acct: "tok")
    monkeypatch.setattr(teams, "_my_id", lambda client, token: "me-guid")
    if list_teams_exc is not None:

        def _raise(client, token):
            raise list_teams_exc

        monkeypatch.setattr(teams, "list_teams", _raise)
    else:
        monkeypatch.setattr(teams, "list_teams", lambda client, token: teams_list)
    monkeypatch.setattr(teams, "list_channels", lambda client, token, team_id: channels or [])
    monkeypatch.setattr(teams, "list_channel_messages", lambda client, token, team_id, channel_id, limit: messages or [])
    return MicrosoftContext(
        cache_file=tmp_path / "cache.bin",
        http_client=MagicMock(),
        log_dir=tmp_path,
        notif_dir=tmp_path / "notif",
        monitor_base_dir=tmp_path,
        monitor_state_file=tmp_path / "state.txt",
        monitor_log_file=tmp_path / "m.log",
        monitor_logger=logging.getLogger("test.teams.channels"),
        monitor_stop_event=MagicMock(),
        scopes=[],
        base_url="",
        upload_chunk_size=1,
        folders={},
    )


def test_poll_teams_channels_emits_non_interrupt_notification(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from microsoft_cli import monitor

    teams_list = [{"id": "team-1", "displayName": "Engineering"}]
    channels = [{"id": "chan-1", "displayName": "General"}]
    messages = [
        {
            "id": "msg-1",
            "createdDateTime": "2026-07-10T12:00:00Z",
            "from": {"user": {"id": "other-guid", "displayName": "Bob"}},
            "body": {"content": "<p>ship it</p>"},
        }
    ]
    ctx = _teams_channels_ctx(tmp_path, monkeypatch, teams_list=teams_list, channels=channels, messages=messages)
    last_dt = datetime(2026, 7, 10, 11, 0, tzinfo=UTC)
    monitor._poll_teams_channels_account(ctx, Config(data_dir=tmp_path), "me@x.com", last_dt, False)

    files = list((tmp_path / "notif").glob("*.json"))
    assert len(files) == 1
    notif = json.loads(files[0].read_text())
    assert notif["type"] == "teams"
    assert notif["sender"] == "Bob"
    assert notif["topic"] == "Engineering / General"
    assert notif["team_id"] == "team-1"
    assert notif["channel_id"] == "chan-1"
    assert "ship it" in notif["preview"]
    # Channel messages are broadcast — they pool rather than interrupt.
    assert "interrupt" not in notif or notif["interrupt"] is False


def test_poll_teams_channels_skips_own_message(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from microsoft_cli import monitor

    teams_list = [{"id": "team-1", "displayName": "Engineering"}]
    channels = [{"id": "chan-1", "displayName": "General"}]
    messages = [
        {
            "id": "msg-1",
            "createdDateTime": "2026-07-10T12:00:00Z",
            "from": {"user": {"id": "me-guid", "displayName": "Me"}},
            "body": {"content": "my own post"},
        }
    ]
    ctx = _teams_channels_ctx(tmp_path, monkeypatch, teams_list=teams_list, channels=channels, messages=messages)
    last_dt = datetime(2026, 7, 10, 11, 0, tzinfo=UTC)
    monitor._poll_teams_channels_account(ctx, Config(data_dir=tmp_path), "me@x.com", last_dt, False)
    assert list((tmp_path / "notif").glob("*.json")) == []


def test_poll_teams_channels_skips_old_message(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from microsoft_cli import monitor

    teams_list = [{"id": "team-1", "displayName": "Engineering"}]
    channels = [{"id": "chan-1", "displayName": "General"}]
    messages = [
        {
            "id": "msg-1",
            "createdDateTime": "2026-07-10T10:00:00Z",
            "from": {"user": {"id": "other-guid", "displayName": "Bob"}},
            "body": {"content": "old news"},
        }
    ]
    ctx = _teams_channels_ctx(tmp_path, monkeypatch, teams_list=teams_list, channels=channels, messages=messages)
    last_dt = datetime(2026, 7, 10, 11, 0, tzinfo=UTC)
    monitor._poll_teams_channels_account(ctx, Config(data_dir=tmp_path), "me@x.com", last_dt, False)
    assert list((tmp_path / "notif").glob("*.json")) == []


def test_poll_teams_channels_degrades_gracefully_on_permission_error(tmp_path, monkeypatch):
    """When the account lacks channel access (403 / TeamsError), the poller returns cleanly with no
    notification and no exception, leaving chats-only behaviour intact."""
    from datetime import UTC, datetime

    from microsoft_cli import monitor

    ctx = _teams_channels_ctx(tmp_path, monkeypatch, teams_list=[], list_teams_exc=_http_error(403))
    last_dt = datetime(2026, 7, 10, 11, 0, tzinfo=UTC)
    # Must not raise.
    monitor._poll_teams_channels_account(ctx, Config(data_dir=tmp_path), "me@x.com", last_dt, False)
    assert list((tmp_path / "notif").glob("*.json")) == []

    # A raised TeamsError degrades the same way.
    ctx2 = _teams_channels_ctx(tmp_path, monkeypatch, teams_list=[], list_teams_exc=teams.TeamsError("nope"))
    monitor._poll_teams_channels_account(ctx2, Config(data_dir=tmp_path), "me@x.com", last_dt, False)
    assert list((tmp_path / "notif").glob("*.json")) == []


def test_poll_teams_skips_old_message(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from microsoft_cli import monitor

    chats = [
        {
            "id": "chat-1",
            "lastMessagePreview": {
                "createdDateTime": "2026-07-10T10:00:00Z",
                "from": {"user": {"id": "other-guid", "displayName": "Bob"}},
                "body": {"content": "old"},
            },
        }
    ]
    ctx = _teams_ctx(tmp_path, monkeypatch, chats)
    last_dt = datetime(2026, 7, 10, 11, 0, tzinfo=UTC)
    monitor._poll_teams_account(ctx, Config(data_dir=tmp_path), "me@x.com", last_dt, False)
    assert list((tmp_path / "notif").glob("*.json")) == []
