"""The notifications skill (notif-interrupt-rules.py) must write the same policy file + shape core
reads, and refuse to write anything core would silently drop (regression guard for issue #925: the
skill once wrote a bare list to a file core no longer read, so rules were silently ignored)."""

import argparse
import importlib.util
import json
import pathlib
import re
import sqlite3

import pytest

import core.models as vm
from core import notification_interrupt_policy as nip

_SKILL_PATH = pathlib.Path(__file__).resolve().parents[1] / "skills" / "notifications" / "scripts" / "notif-interrupt-rules.py"


def _load_skill(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("notif_rules_skill", _SKILL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Redirect the module's hardcoded ~/agent/data path at the same place core's data_dir resolves.
    monkeypatch.setattr(module, "POLICY_PATH", tmp_path / "data" / "notification_policy.json")
    return module


def test_skill_writes_a_rule_core_reads_and_applies(tmp_path, monkeypatch):
    skill = _load_skill(tmp_path, monkeypatch)
    skill.cmd_add(argparse.Namespace(source="app-chat", type=None, sender=None, keyword=None, match=None, action="pool"))

    # The exact file + shape core reads, validated by core's own model.
    config = vm.VestaConfig(agent_dir=tmp_path)
    rules = nip.load_rules(config)
    assert len(rules) == 1
    assert rules[0].source == "app-chat"
    assert rules[0].action == "pool"


def test_skill_and_core_agree_on_the_rule_key_set(tmp_path, monkeypatch):
    # If core's model grows/loses a field, this fails — forcing the skill's RULE_KEYS to be updated
    # in step rather than silently drifting (the root cause of #925).
    skill = _load_skill(tmp_path, monkeypatch)
    assert skill.RULE_KEYS == set(nip.NotificationInterruptRule.model_fields)
    assert skill.DEFAULT_KEYS == set(nip.NotificationDefault.model_fields)


def _seed_events(db_path: pathlib.Path, notifications: list[dict]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, data TEXT)")
    for notif in notifications:
        conn.execute("INSERT INTO events (ts, data) VALUES (?, ?)", ("t", json.dumps(notif)))
    conn.commit()
    conn.close()


def test_set_default_toggles_an_observed_pair_but_refuses_to_invent_one(tmp_path, monkeypatch):
    skill = _load_skill(tmp_path, monkeypatch)
    db = tmp_path / "data" / "events.db"
    _seed_events(db, [{"type": "notification", "source": "app-chat", "notif_type": "message"}])
    monkeypatch.setattr(skill, "EVENTS_DB", db)

    # The observed (app-chat, message) pair can be toggled, and core reads the override.
    assert skill.cmd_set_default(argparse.Namespace(source="app-chat", type="message", action="pool")) == 0
    defaults = nip.load_defaults(vm.VestaConfig(agent_dir=tmp_path))
    assert any(d.source == "app-chat" and d.type == "message" and d.action == "pool" for d in defaults)

    # app-chat with no type was never received (every app-chat notif has type=message) -> refused,
    # so the agent can't add a phantom "app-chat / — " fallback row.
    assert skill.cmd_set_default(argparse.Namespace(source="app-chat", type="", action="interrupt")) == 1


@pytest.mark.parametrize(
    "bad_rule",
    [
        {"source": "x", "action": "bogus"},  # action core would reject
        {"weird": 1, "action": "pool"},  # unknown field (core forbids extras)
        {"source": "core", "action": "pool"},  # core source is never targetable
        {"match": [{"field": "body", "op": "regex", "value": "(unclosed"}], "action": "pool"},  # invalid predicate regex
        {"match": [{"field": "x", "value": "y", "bogus": 1}], "action": "pool"},  # predicate has a field core forbids
    ],
)
def test_write_guard_refuses_a_section_core_would_drop(tmp_path, monkeypatch, bad_rule):
    skill = _load_skill(tmp_path, monkeypatch)
    with pytest.raises((ValueError, re.error)):
        skill.save_section("rules", [bad_rule])
    # Nothing was written, so core sees no rules rather than a malformed file.
    assert not (tmp_path / "data" / "notification_policy.json").exists()
