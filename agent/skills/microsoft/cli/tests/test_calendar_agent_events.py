"""Events the agent creates carry the agent category, and every read shows it."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
from microsoft_cli import calendar, owa_rest
from microsoft_cli import format as fmt
from microsoft_cli.config import Config
from microsoft_cli.payloads import AGENT_EVENT_CATEGORY, EventFields

ACCOUNT = "user@example.com"
EVENT = EventFields(subject="Standup", start="2026-08-15T10:00:00", end="2026-08-15T10:30:00", timezone="UTC")


def _owa_cfg(tmp_path: Path) -> SimpleNamespace:
    cfg = SimpleNamespace(data_dir=tmp_path)
    owa_rest.save_token(ACCOUNT, cfg, token="test-tok", expires_at=time.time() + 7200)
    return cfg


def _owa_client(json_response: dict) -> httpx.Client:
    mock = MagicMock(spec=httpx.Client)
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.content = b"{}"
    resp.json.return_value = json_response
    resp.raise_for_status = MagicMock()
    mock.get.return_value = resp
    mock.post.return_value = resp
    return mock


def _event(subject: str, categories: list[str] | None = None) -> dict:
    row = {
        "id": "evt1",
        "subject": subject,
        "start": {"dateTime": "2026-08-15T10:00:00"},
        "end": {"dateTime": "2026-08-15T10:30:00"},
        "location": {"displayName": "Zoom"},
    }
    if categories is not None:
        row["categories"] = categories
    return row


def test_graph_create_event_stamps_the_agent_category(monkeypatch):
    posted: list[dict] = []

    def request(_config, _client, method, path, _account_id, **kwargs):
        posted.append(kwargs["json"])
        return {"id": "evt1"}

    monkeypatch.setattr(calendar.auth, "get_account_id_by_email", lambda *_args: "acct-1")
    monkeypatch.setattr(calendar.graph, "request_cfg", request)

    calendar.create_event(Config(), None, account_email=ACCOUNT, event=EVENT)

    assert posted[0]["categories"] == [AGENT_EVENT_CATEGORY]


def test_owa_rest_create_event_stamps_the_agent_category(tmp_path):
    client = _owa_client({"Id": "evt1"})

    owa_rest.create_event(client, ACCOUNT, _owa_cfg(tmp_path), event=EVENT)

    assert client.post.call_args.kwargs["json"]["Categories"] == [AGENT_EVENT_CATEGORY]


def test_both_backends_select_categories_on_every_event_read(tmp_path, monkeypatch):
    selects: list[str] = []

    def paginate(_config, _client, _endpoint, _account_id, **kwargs):
        selects.append(kwargs["params"]["$select"])
        return iter(())

    monkeypatch.setattr(calendar.auth, "get_account_id_by_email", lambda *_args: "acct-1")
    monkeypatch.setattr(calendar.graph, "paginate_cfg", paginate)
    calendar.list_events(Config(), None, account_email=ACCOUNT, include_details=True, user_timezone="UTC")
    calendar.list_events(Config(), None, account_email=ACCOUNT, include_details=False, user_timezone="UTC")

    client = _owa_client({"value": []})
    owa_rest.list_events(client, ACCOUNT, _owa_cfg(tmp_path), start_utc="2026-08-15T00:00:00Z", end_utc="2026-08-16T00:00:00Z")
    selects.append(client.get.call_args.kwargs["params"]["$select"])

    assert [s.split(",")[-1] for s in selects] == ["categories", "categories", "Categories"]


def test_list_prefixes_an_agent_created_event():
    out = fmt.format_calendar_event_list([_event("Standup", ["Sport", AGENT_EVENT_CATEGORY])])
    assert f"[{AGENT_EVENT_CATEGORY}] Standup" in out


def test_list_leaves_a_user_event_alone():
    out = fmt.format_calendar_event_list([_event("Dentist", []), _event("Offsite", ["Work"]), _event("Padel")])
    assert f"[{AGENT_EVENT_CATEGORY}]" not in out
    assert all(subject in out for subject in ("Dentist", "Offsite", "Padel"))


def test_the_mark_keeps_the_row_shape():
    marked = fmt.format_calendar_event_list([_event("Standup", [AGENT_EVENT_CATEGORY])]).split("\t")
    plain = fmt.format_calendar_event_list([_event("Standup", [])]).split("\t")
    assert len(plain) == 5
    assert marked[2] == f"[{AGENT_EVENT_CATEGORY}] Standup"
    assert marked[:2] + marked[3:] == plain[:2] + plain[3:]
