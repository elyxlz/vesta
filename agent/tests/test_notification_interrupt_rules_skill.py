"""E2e for the notification-interrupt-rules skill CLI: it writes rules the core engine can load and apply."""

import datetime as dt
import os
import pathlib as pl
import subprocess
import sys

import core.models as vm
from core import notification_interrupt_policy as npn
from core.events import EventBus, NotificationEvent

SCRIPT = pl.Path(__file__).resolve().parents[1] / "skills" / "notifications" / "scripts" / "notif-interrupt-rules.py"


def _run(home: pl.Path, *args: str) -> subprocess.CompletedProcess[str]:
    # The script resolves the rules file under $HOME/agent/data, so point HOME at a tmp dir.
    return subprocess.run([sys.executable, str(SCRIPT), *args], env={**os.environ, "HOME": str(home)}, capture_output=True, text=True)


def _config(home: pl.Path) -> vm.VestaConfig:
    return vm.VestaConfig(agent_dir=home / "agent")


def _seed_notification(home: pl.Path, source: str, notif_type: str) -> None:
    """Record one notification so the toggle-only set-default sees (source, type) as observed.

    set-default can only flip the default of a (source, type) the agent has actually received, so the
    override tests must first put that pair in the history the script reads (same events.db, via HOME)."""
    bus = EventBus(data_dir=home / "agent" / "data")
    event: NotificationEvent = {
        "type": "notification",
        "source": source,
        "summary": "x",
        "notif_type": notif_type,
        "interrupt": False,
        "decided": "pool",
        "notif_id": f"{source}-{notif_type}-seed",
    }
    try:
        bus.emit(event)
    finally:
        bus.close()


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
    # Two equally-specific rules (1 condition each) keep insertion order: the second appends after.
    _run(tmp_path, "add", "--source", "whatsapp", "--action", "interrupt")
    _run(tmp_path, "add", "--source", "twitter", "--action", "pool")
    rules = npn.load_rules(_config(tmp_path))
    assert [r.action for r in rules] == ["interrupt", "pool"]


def _ids(tmp_path):
    return [r.id for r in npn.load_rules(_config(tmp_path))]


def test_add_auto_places_specific_above_broad(tmp_path):
    # Broad pool rule first, then a narrower interrupt exception: the exception must land ABOVE the
    # broad rule so first-match-wins reaches it instead of being shadowed.
    _run(tmp_path, "add", "--source", "whatsapp", "--action", "pool")
    _run(tmp_path, "add", "--source", "whatsapp", "--sender", "wife", "--action", "interrupt")
    rules = npn.load_rules(_config(tmp_path))
    assert [r.action for r in rules] == ["interrupt", "pool"]


def test_add_auto_places_broad_below_specific(tmp_path):
    # Reverse insertion order: a later broad rule still sinks below the existing specific one.
    _run(tmp_path, "add", "--source", "whatsapp", "--match", "chat_name=Bride squad", "--action", "interrupt")
    _run(tmp_path, "add", "--source", "whatsapp", "--action", "pool")
    rules = npn.load_rules(_config(tmp_path))
    assert [r.action for r in rules] == ["interrupt", "pool"]


def test_add_before_and_after_place_explicitly(tmp_path):
    _run(tmp_path, "add", "--source", "a", "--action", "pool")
    _run(tmp_path, "add", "--source", "b", "--action", "pool")
    first, second = _ids(tmp_path)
    _run(tmp_path, "add", "--source", "c", "--action", "pool", "--before", second)
    assert [r.source for r in npn.load_rules(_config(tmp_path))] == ["a", "c", "b"]
    _run(tmp_path, "add", "--source", "d", "--action", "pool", "--after", first)
    assert [r.source for r in npn.load_rules(_config(tmp_path))] == ["a", "d", "c", "b"]


def test_add_before_unknown_id_errors(tmp_path):
    _run(tmp_path, "add", "--source", "a", "--action", "pool")
    result = _run(tmp_path, "add", "--source", "b", "--action", "pool", "--before", "nope")
    assert result.returncode == 1
    # The rejected add did not write anything.
    assert [r.source for r in npn.load_rules(_config(tmp_path))] == ["a"]


def test_move_top_bottom_before_after(tmp_path):
    # Three equally-specific rules keep insertion order a, b, c.
    _run(tmp_path, "add", "--source", "a", "--action", "pool")
    _run(tmp_path, "add", "--source", "b", "--action", "pool")
    _run(tmp_path, "add", "--source", "c", "--action", "pool")
    id_a, id_b, id_c = _ids(tmp_path)
    _run(tmp_path, "move", id_c, "--top")
    assert [r.source for r in npn.load_rules(_config(tmp_path))] == ["c", "a", "b"]
    _run(tmp_path, "move", id_c, "--bottom")
    assert [r.source for r in npn.load_rules(_config(tmp_path))] == ["a", "b", "c"]
    _run(tmp_path, "move", id_a, "--after", id_b)
    assert [r.source for r in npn.load_rules(_config(tmp_path))] == ["b", "a", "c"]
    _run(tmp_path, "move", id_c, "--before", id_b)
    assert [r.source for r in npn.load_rules(_config(tmp_path))] == ["c", "b", "a"]


def test_move_unknown_id_errors(tmp_path):
    _run(tmp_path, "add", "--source", "a", "--action", "pool")
    result = _run(tmp_path, "move", "nope", "--top")
    assert result.returncode == 1


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


def test_facets_surface_structured_extra_fields(tmp_path):
    import json as _json

    from core.events import EventBus

    bus = EventBus(data_dir=tmp_path / "agent" / "data")
    try:
        bus.emit(
            {
                "type": "notification",
                "source": "whatsapp",
                "summary": "x",
                "notif_type": "message",
                "sender": "Alice",
                "fields": {"chat_name": "Bride squad", "chat_type": "group"},
                "interrupt": True,
                "decided": "pool",
                "notif_id": "n1",
            }
        )
        bus.emit(
            {
                "type": "notification",
                "source": "whatsapp",
                "summary": "x",
                "notif_type": "message",
                "sender": "Bob",
                "fields": {"chat_name": "Work standup", "chat_type": "group"},
                "interrupt": True,
                "decided": "pool",
                "notif_id": "n2",
            }
        )
    finally:
        bus.close()

    result = _run(tmp_path, "facets")
    assert result.returncode == 0, result.stderr
    fields = _json.loads(result.stdout)["fields"]
    assert set(fields["chat_name"]) == {"Bride squad", "Work standup"}
    assert fields["chat_type"] == ["group"]  # deduped


def test_facets_empty_when_no_history(tmp_path):
    import json as _json

    result = _run(tmp_path, "facets")
    assert result.returncode == 0, result.stderr
    assert _json.loads(result.stdout) == {"source": [], "type": [], "sender": [], "fields": {}}


def test_add_rejects_core_source(tmp_path):
    result = _run(tmp_path, "add", "--source", "core", "--action", "pool")
    assert result.returncode == 1
    assert npn.load_rules(_config(tmp_path)) == []


def test_add_accepts_keyword_regex(tmp_path):
    result = _run(tmp_path, "add", "--keyword", "invoice|payment", "--action", "interrupt")
    assert result.returncode == 0, result.stderr
    rules = npn.load_rules(_config(tmp_path))
    # --keyword is sugar that compiles to a regex predicate over the body/message text alias.
    assert len(rules) == 1
    assert rules[0].match == [npn.FieldPredicate(field="text", op="regex", value="invoice|payment")]


def test_add_match_targets_arbitrary_field(tmp_path):
    result = _run(tmp_path, "add", "--source", "whatsapp", "--match", "chat_name=Bride squad", "--action", "pool")
    assert result.returncode == 0, result.stderr
    rules = npn.load_rules(_config(tmp_path))
    assert rules[0].source == "whatsapp"
    assert rules[0].match == [npn.FieldPredicate(field="chat_name", op="contains", value="Bride squad")]
    # And it applies: a message in that group is pooled, a 1:1 is not.
    group = vm.Notification.model_validate(
        {"timestamp": "2025-01-01T00:00:00", "source": "whatsapp", "type": "message", "chat_name": "Bride squad", "interrupt": True}
    )
    dm = vm.Notification.model_validate(
        {"timestamp": "2025-01-01T00:00:00", "source": "whatsapp", "type": "message", "contact_name": "Alice", "interrupt": True}
    )
    assert npn.should_interrupt(group, rules) is False
    assert npn.should_interrupt(dm, rules) is True


def test_add_match_regex_and_negate_ops(tmp_path):
    _run(tmp_path, "add", "--match", "chat_name~=^proj-", "--match", "chat_type!=group", "--action", "pool")
    rules = npn.load_rules(_config(tmp_path))
    assert rules[0].match == [
        npn.FieldPredicate(field="chat_name", op="regex", value="^proj-"),
        npn.FieldPredicate(field="chat_type", op="contains", value="group", negate=True),
    ]


def test_add_match_trims_value_whitespace(tmp_path):
    # A stray space after '=' must not become part of the value (web trims; CLI must match).
    _run(tmp_path, "add", "--match", "chat_name= Bride squad ", "--action", "pool")
    rules = npn.load_rules(_config(tmp_path))
    assert rules[0].match == [npn.FieldPredicate(field="chat_name", op="contains", value="Bride squad")]


def test_add_rejects_invalid_match_regex(tmp_path):
    result = _run(tmp_path, "add", "--match", "chat_name~=(unclosed", "--action", "pool")
    assert result.returncode == 1
    assert npn.load_rules(_config(tmp_path)) == []


def test_add_rejects_malformed_match(tmp_path):
    result = _run(tmp_path, "add", "--match", "no-operator-here", "--action", "pool")
    assert result.returncode == 1
    assert npn.load_rules(_config(tmp_path)) == []


def test_legacy_rule_on_disk_is_normalized_then_converges(tmp_path):
    # A rule written by the pre-update CLI (flat sender/keyword keys) must keep working and, once the
    # file is rewritten by any edit, converge to canonical match shape.
    policy = tmp_path / "agent" / "data" / "notification_policy.json"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(
        '{"rules": [{"id": "old", "source": "whatsapp", "type": null, "sender": "wife", "keyword": null, "action": "interrupt"}]}'
    )
    rules = npn.load_rules(_config(tmp_path))
    assert rules[0].match == [npn.FieldPredicate(field="sender", op="contains", value="wife")]
    # Adding another rule rewrites the file; the legacy one is now canonical.
    _run(tmp_path, "add", "--source", "twitter", "--action", "pool")
    import json as _json

    on_disk = _json.loads(policy.read_text())["rules"]
    assert "sender" not in on_disk[0] and "keyword" not in on_disk[0]
    assert on_disk[0]["match"] == [{"field": "sender", "op": "contains", "value": "wife", "negate": False}]


def test_add_rejects_invalid_keyword_regex(tmp_path):
    result = _run(tmp_path, "add", "--keyword", "(unclosed", "--action", "interrupt")
    assert result.returncode == 1
    assert "invalid" in result.stderr.lower()
    assert npn.load_rules(_config(tmp_path)) == []


def test_set_default_writes_engine_loadable_override(tmp_path):
    _seed_notification(tmp_path, "outlook", "message")
    result = _run(tmp_path, "set-default", "--source", "outlook", "--type", "message", "--action", "pool")
    assert result.returncode == 0, result.stderr
    defaults = npn.load_defaults(_config(tmp_path))
    assert len(defaults) == 1
    assert defaults[0].source == "outlook" and defaults[0].type == "message" and defaults[0].action == "pool"


def test_set_default_replaces_same_source_type(tmp_path):
    _seed_notification(tmp_path, "outlook", "")
    _run(tmp_path, "set-default", "--source", "outlook", "--action", "pool")
    _run(tmp_path, "set-default", "--source", "outlook", "--action", "interrupt")
    defaults = npn.load_defaults(_config(tmp_path))
    assert len(defaults) == 1 and defaults[0].action == "interrupt"


def test_clear_default_removes_override(tmp_path):
    _seed_notification(tmp_path, "outlook", "")
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
