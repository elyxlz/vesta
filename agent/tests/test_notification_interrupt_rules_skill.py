"""E2e for the notification-interrupt-rules skill CLI: it writes rules the core engine can load and apply."""

import datetime as dt
import os
import pathlib as pl
import subprocess
import sys

import core.models as vm
from core import notification_interrupt_policy as npn

SCRIPT = pl.Path(__file__).resolve().parents[1] / "skills" / "notifications" / "scripts" / "notif-interrupt-rules.py"


def _run(home: pl.Path, *args: str) -> subprocess.CompletedProcess[str]:
    # The script resolves the rules file under $HOME/agent/data, so point HOME at a tmp dir.
    return subprocess.run([sys.executable, str(SCRIPT), *args], env={**os.environ, "HOME": str(home)}, capture_output=True, text=True)


def _config(home: pl.Path) -> vm.VestaConfig:
    return vm.VestaConfig(agent_dir=home / "agent")


def test_list_empty(tmp_path):
    result = _run(tmp_path, "list")
    assert result.returncode == 0, result.stderr
    assert "No rules" in result.stdout


def test_add_writes_engine_loadable_rule_and_applies(tmp_path):
    result = _run(tmp_path, "add", "--source", "twitter", "--action", "pool")
    assert result.returncode == 0, result.stderr

    rules = npn.load_rules(_config(tmp_path))
    assert len(rules) == 1
    assert rules[0].source == "twitter"
    assert rules[0].action == "pool"
    assert rules[0].id

    # The decision the monitor loop makes now uses the rule: a static-interrupt tweet is pooled.
    notif = vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="twitter", type="tweet", interrupt=True)
    assert npn.should_interrupt(notif, rules) is False


def test_add_catch_all_has_no_conditions(tmp_path):
    result = _run(tmp_path, "add", "--action", "pool")
    assert result.returncode == 0, result.stderr
    rules = npn.load_rules(_config(tmp_path))
    assert rules[0].source is None and rules[0].type is None and rules[0].action == "pool"


def test_add_preserves_order(tmp_path):
    _run(tmp_path, "add", "--source", "whatsapp", "--sender", "wife", "--action", "interrupt")
    _run(tmp_path, "add", "--source", "twitter", "--action", "pool")
    rules = npn.load_rules(_config(tmp_path))
    assert [r.action for r in rules] == ["interrupt", "pool"]


def test_remove_by_id(tmp_path):
    _run(tmp_path, "add", "--source", "twitter", "--action", "pool")
    rule_id = npn.load_rules(_config(tmp_path))[0].id
    result = _run(tmp_path, "remove", rule_id)
    assert result.returncode == 0, result.stderr
    assert npn.load_rules(_config(tmp_path)) == []


def test_remove_unknown_id_errors(tmp_path):
    result = _run(tmp_path, "remove", "does-not-exist")
    assert result.returncode == 1


def test_clear(tmp_path):
    _run(tmp_path, "add", "--source", "x", "--action", "interrupt")
    _run(tmp_path, "add", "--source", "y", "--action", "pool")
    assert len(npn.load_rules(_config(tmp_path))) == 2
    result = _run(tmp_path, "clear")
    assert result.returncode == 0, result.stderr
    assert npn.load_rules(_config(tmp_path)) == []


def test_invalid_action_rejected(tmp_path):
    result = _run(tmp_path, "add", "--source", "x", "--action", "nope")
    assert result.returncode != 0  # argparse choices rejects it
    assert npn.load_rules(_config(tmp_path)) == []


def test_facets_lists_values_from_notification_history(tmp_path):
    import json as _json

    from core.events import EventBus

    bus = EventBus(data_dir=tmp_path / "agent" / "data")
    try:
        bus.emit({"type": "user", "text": "ignore me"})
        bus.emit(
            {
                "type": "notification",
                "source": "twitter",
                "summary": "x",
                "notif_type": "tweet",
                "sender": "@bob",
                "interrupt": True,
                "decided": "interrupt",
                "notif_id": "n1",
            }
        )
        bus.emit(
            {
                "type": "notification",
                "source": "whatsapp",
                "summary": "x",
                "notif_type": "message",
                "sender": "Alice",
                "interrupt": True,
                "decided": "pool",
                "notif_id": "n2",
            }
        )
    finally:
        bus.close()

    result = _run(tmp_path, "facets")
    assert result.returncode == 0, result.stderr
    facets = _json.loads(result.stdout)
    assert set(facets["source"]) == {"twitter", "whatsapp"}
    assert set(facets["type"]) == {"tweet", "message"}
    assert set(facets["sender"]) == {"@bob", "Alice"}


def test_facets_empty_when_no_history(tmp_path):
    import json as _json

    result = _run(tmp_path, "facets")
    assert result.returncode == 0, result.stderr
    assert _json.loads(result.stdout) == {"source": [], "type": [], "sender": []}


def test_add_rejects_core_source(tmp_path):
    result = _run(tmp_path, "add", "--source", "core", "--action", "pool")
    assert result.returncode == 1
    assert npn.load_rules(_config(tmp_path)) == []


def test_add_accepts_keyword_regex(tmp_path):
    result = _run(tmp_path, "add", "--keyword", "invoice|payment", "--action", "interrupt")
    assert result.returncode == 0, result.stderr
    rules = npn.load_rules(_config(tmp_path))
    assert len(rules) == 1 and rules[0].keyword == "invoice|payment"


def test_add_rejects_invalid_keyword_regex(tmp_path):
    result = _run(tmp_path, "add", "--keyword", "(unclosed", "--action", "interrupt")
    assert result.returncode == 1
    assert "invalid" in result.stderr.lower()
    assert npn.load_rules(_config(tmp_path)) == []


def test_set_default_writes_engine_loadable_override(tmp_path):
    result = _run(tmp_path, "set-default", "--source", "outlook", "--type", "message", "--action", "pool")
    assert result.returncode == 0, result.stderr
    defaults = npn.load_defaults(_config(tmp_path))
    assert len(defaults) == 1
    assert defaults[0].source == "outlook" and defaults[0].type == "message" and defaults[0].action == "pool"


def test_set_default_replaces_same_source_type(tmp_path):
    _run(tmp_path, "set-default", "--source", "outlook", "--action", "pool")
    _run(tmp_path, "set-default", "--source", "outlook", "--action", "interrupt")
    defaults = npn.load_defaults(_config(tmp_path))
    assert len(defaults) == 1 and defaults[0].action == "interrupt"


def test_clear_default_removes_override(tmp_path):
    _run(tmp_path, "set-default", "--source", "outlook", "--action", "pool")
    result = _run(tmp_path, "clear-default", "--source", "outlook")
    assert result.returncode == 0, result.stderr
    assert npn.load_defaults(_config(tmp_path)) == []


def test_clear_default_unknown_errors(tmp_path):
    result = _run(tmp_path, "clear-default", "--source", "nope")
    assert result.returncode == 1


def test_set_default_rejects_core_source(tmp_path):
    result = _run(tmp_path, "set-default", "--source", "core", "--action", "pool")
    assert result.returncode == 1
    assert npn.load_defaults(_config(tmp_path)) == []
