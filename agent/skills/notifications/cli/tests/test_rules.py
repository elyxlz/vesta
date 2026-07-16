import argparse
import json
import sqlite3

import pytest

from notifications_cli import cli


def _args(**kwargs) -> argparse.Namespace:
    base = {"source": None, "type": None, "sender": None, "keyword": None, "match": None, "before": None, "after": None}
    base.update(kwargs)
    return argparse.Namespace(**base)


def _store(monkeypatch):
    """Back get_rules/put_rules with an in-memory list so command tests need no server."""
    state: list[dict[str, object]] = []
    monkeypatch.setattr(cli, "get_rules", lambda: list(state))
    monkeypatch.setattr(cli, "put_rules", lambda rules: state.__setitem__(slice(None), rules))
    return state


def test_parse_match_ops():
    assert cli._parse_match("chat_name=Bride squad") == {"field": "chat_name", "op": "contains", "value": "Bride squad", "negate": False}
    assert cli._parse_match("chat_name~=^proj-") == {"field": "chat_name", "op": "regex", "value": "^proj-", "negate": False}
    assert cli._parse_match("chat_type!=group") == {"field": "chat_type", "op": "contains", "value": "group", "negate": True}
    assert cli._parse_match("chat_name!~=^x") == {"field": "chat_name", "op": "regex", "value": "^x", "negate": True}


def test_parse_match_rejects_bad_regex():
    with pytest.raises(__import__("re").error):
        cli._parse_match("chat_name~=(unclosed")


def test_add_builds_match_predicates_from_shortcuts(monkeypatch, capsys):
    store = _store(monkeypatch)
    rc = cli.cmd_add(_args(action="snooze", source="whatsapp", sender="wife", keyword="urgent"))
    assert rc == 0
    rule = store[0]
    assert rule["source"] == "whatsapp" and rule["action"] == "snooze" and rule["id"]
    assert rule["match"] == [
        {"field": "sender", "op": "contains", "value": "wife", "negate": False},
        {"field": "text", "op": "regex", "value": "urgent", "negate": False},
    ]
    assert "applies next tick" in capsys.readouterr().out


def test_add_builds_trash_rule(monkeypatch, capsys):
    store = _store(monkeypatch)
    rc = cli.cmd_add(_args(action="trash", source="whatsapp", match=["chat_name=status"]))
    assert rc == 0
    rule = store[0]
    assert rule["action"] == "trash" and rule["source"] == "whatsapp"
    assert rule["match"] == [{"field": "chat_name", "op": "contains", "value": "status", "negate": False}]
    assert "-> trash" in capsys.readouterr().out


def test_add_rejects_core_source(monkeypatch, capsys):
    _store(monkeypatch)
    assert cli.cmd_add(_args(action="snooze", source="core")) == 1
    assert "core notifications" in capsys.readouterr().err


def test_add_auto_places_specific_rule_above_broader(monkeypatch):
    store = _store(monkeypatch)
    cli.cmd_add(_args(action="snooze", source="whatsapp"))  # broad
    cli.cmd_add(_args(action="interrupt", source="whatsapp", sender="wife"))  # narrower -> above
    assert [r["action"] for r in store] == ["interrupt", "snooze"]


def test_move_to_top(monkeypatch):
    store = _store(monkeypatch)
    cli.cmd_add(_args(action="snooze", source="a"))
    cli.cmd_add(_args(action="snooze", source="b"))
    bottom_id = store[1]["id"]
    assert cli.cmd_move(argparse.Namespace(id=bottom_id, before=None, after=None, to_top=True, to_bottom=False)) == 0
    assert store[0]["id"] == bottom_id


def test_remove_missing_reports_error(monkeypatch, capsys):
    _store(monkeypatch)
    assert cli.cmd_remove(_args(id="nope")) == 1
    assert "No rule with id nope" in capsys.readouterr().err


def test_remove_and_clear(monkeypatch):
    store = _store(monkeypatch)
    cli.cmd_add(_args(action="snooze", source="a"))
    rid = store[0]["id"]
    assert cli.cmd_remove(_args(id=rid)) == 0
    assert store == []
    cli.cmd_add(_args(action="snooze", source="b"))
    assert cli.cmd_clear(_args()) == 0
    assert store == []


def test_facets_reads_notification_history(monkeypatch, tmp_path, capsys):
    db = tmp_path / "events.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, data TEXT)")
    conn.executemany(
        "INSERT INTO events (data) VALUES (?)",
        [
            (
                json.dumps(
                    {
                        "type": "notification",
                        "source": "whatsapp",
                        "notif_type": "message",
                        "sender": "bob",
                        "fields": {"chat_name": "Bride squad"},
                    }
                ),
            ),
            (json.dumps({"type": "notification", "source": "twitter", "notif_type": "tweet", "sender": "alice"}),),
            (json.dumps({"type": "chat", "source": "ignored"}),),
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(cli, "EVENTS_DB", db)
    assert cli.cmd_facets(_args()) == 0
    facets = json.loads(capsys.readouterr().out)
    assert set(facets["source"]) == {"whatsapp", "twitter"}
    assert facets["fields"]["chat_name"] == ["Bride squad"]
