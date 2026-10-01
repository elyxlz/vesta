"""`calendar update` attendee edits merge into the event's current list on both backends."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from microsoft_cli import calendar, cli, owa_rest
from microsoft_cli.config import Config
from microsoft_cli.payloads import EventPatch

ACCOUNT = "user@example.com"


def _attendee(address: str, kind: str = "required") -> dict:
    return {"emailAddress": {"address": address, "name": address.split("@", maxsplit=1)[0]}, "type": kind, "status": {"response": "accepted"}}


CURRENT = [_attendee("a@example.com"), _attendee("b@example.com", "optional")]


def _graph(monkeypatch, current: list[dict]) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []

    def request(_config, _client, method, path, _account_id, **kwargs):
        calls.append((method, kwargs))
        if method == "GET":
            return {"id": "evt1", "attendees": current}
        return {"id": "evt1"}

    monkeypatch.setattr(calendar.auth, "get_account_id_by_email", lambda *_args: "acct-1")
    monkeypatch.setattr(calendar.graph, "request_cfg", request)
    return calls


def _addresses(attendees: list[dict]) -> list[str]:
    return [a["emailAddress"]["address"] for a in attendees]


def test_graph_add_attendee_keeps_existing_ones(monkeypatch):
    calls = _graph(monkeypatch, CURRENT)

    calendar.update_event(Config(), None, account_email=ACCOUNT, event_id="evt1", patch=EventPatch(add_attendees=["c@example.com"]))

    assert [m for m, _ in calls] == ["GET", "PATCH"]
    sent = calls[1][1]["json"]["attendees"]
    assert _addresses(sent) == ["a@example.com", "b@example.com", "c@example.com"]
    assert [a["type"] for a in sent] == ["required", "optional", "required"]
    assert all("status" not in a for a in sent)


def test_graph_add_existing_attendee_is_case_insensitive_noop(monkeypatch):
    calls = _graph(monkeypatch, CURRENT)

    calendar.update_event(Config(), None, account_email=ACCOUNT, event_id="evt1", patch=EventPatch(add_attendees=["A@Example.com"]))

    assert _addresses(calls[1][1]["json"]["attendees"]) == ["a@example.com", "b@example.com"]


def test_graph_remove_attendee(monkeypatch):
    calls = _graph(monkeypatch, CURRENT)

    calendar.update_event(Config(), None, account_email=ACCOUNT, event_id="evt1", patch=EventPatch(remove_attendees=["B@example.com"]))

    assert _addresses(calls[1][1]["json"]["attendees"]) == ["a@example.com"]


def test_graph_no_attendee_flags_skips_the_read(monkeypatch):
    calls = _graph(monkeypatch, CURRENT)

    calendar.update_event(Config(), None, account_email=ACCOUNT, event_id="evt1", patch=EventPatch(subject="New"))

    assert [m for m, _ in calls] == ["PATCH"]
    assert "attendees" not in calls[0][1]["json"]


def test_graph_attendee_edit_alone_counts_as_an_update(monkeypatch):
    _graph(monkeypatch, [])
    calendar.update_event(Config(), None, account_email=ACCOUNT, event_id="evt1", patch=EventPatch(add_attendees=["c@example.com"]))
    with pytest.raises(ValueError, match="at least one field"):
        calendar.update_event(Config(), None, account_email=ACCOUNT, event_id="evt1", patch=EventPatch())


def test_owa_rest_add_and_remove_attendees(tmp_path: Path):
    cfg = SimpleNamespace(data_dir=tmp_path)
    owa_rest.save_token(ACCOUNT, cfg, token="test-tok", expires_at=time.time() + 7200)
    client = MagicMock(spec=httpx.Client)
    got = MagicMock(spec=httpx.Response)
    got.json.return_value = {
        "Id": "evt1",
        "Attendees": [
            {"EmailAddress": {"Address": "a@example.com"}, "Type": "Required"},
            {"EmailAddress": {"Address": "b@example.com"}, "Type": "Optional"},
        ],
    }
    got.raise_for_status = MagicMock()
    patched = MagicMock(spec=httpx.Response)
    patched.content = b""
    patched.raise_for_status = MagicMock()
    client.get.return_value = got
    client.patch.return_value = patched

    patch = EventPatch(add_attendees=["c@example.com", "A@example.com"], remove_attendees=["b@example.com"])
    owa_rest.update_event(client, ACCOUNT, cfg, event_id="evt1", patch=patch)

    assert client.get.call_args.kwargs["params"]["$select"] == "Attendees"
    sent = client.patch.call_args.kwargs["json"]["Attendees"]
    assert [a["EmailAddress"]["Address"] for a in sent] == ["a@example.com", "c@example.com"]
    assert [a["Type"] for a in sent] == ["Required", "required"]


def test_cli_parses_repeatable_attendee_flags():
    args = cli.build_parser().parse_args(
        [
            "calendar",
            "update",
            "--account",
            ACCOUNT,
            "--id",
            "evt1",
            "--add-attendee",
            "c@example.com",
            "--add-attendee",
            "d@example.com",
            "--remove-attendee",
            "a@example.com",
        ]
    )
    assert args.add_attendees == ["c@example.com", "d@example.com"]
    assert args.remove_attendees == ["a@example.com"]
