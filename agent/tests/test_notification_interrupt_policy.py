"""Tests for the notification interrupt policy: matching, decision, and the rules store."""

import datetime as dt
import json

import pydantic as pyd
import pytest

import core.models as vm
from core import notification_interrupt_policy as npn


def _notif(**fields) -> vm.Notification:
    base = {"timestamp": dt.datetime(2025, 1, 1), "source": "twitter", "type": "tweet"}
    base.update(fields)
    return vm.Notification.model_validate(base)


def _rule(**fields) -> npn.NotificationInterruptRule:
    return npn.NotificationInterruptRule(**fields)


# --- matching + should_interrupt ---


def test_no_rules_falls_back_to_static_interrupt_true():
    assert npn.should_interrupt(_notif(interrupt=True), []) is True


def test_no_rules_falls_back_to_static_interrupt_false():
    assert npn.should_interrupt(_notif(interrupt=False), []) is False


def test_source_rule_overrides_static_flag_to_pool():
    notif = _notif(interrupt=True)
    rules = [_rule(source="twitter", action="pool")]
    assert npn.should_interrupt(notif, rules) is False


def test_source_rule_overrides_static_flag_to_interrupt():
    notif = _notif(interrupt=False)
    rules = [_rule(source="twitter", action="interrupt")]
    assert npn.should_interrupt(notif, rules) is True


def test_source_match_is_case_insensitive():
    notif = _notif(source="Twitter", interrupt=True)
    assert npn.should_interrupt(notif, [_rule(source="twitter", action="pool")]) is False


def test_type_rule_matches():
    notif = _notif(type="tweet", interrupt=True)
    assert npn.should_interrupt(notif, [_rule(type="tweet", action="pool")]) is False


def test_conditions_are_anded_within_a_rule():
    # source matches but type does not -> rule does not apply -> falls back to static flag
    notif = _notif(source="twitter", type="dm", interrupt=True)
    rules = [_rule(source="twitter", type="tweet", action="pool")]
    assert npn.should_interrupt(notif, rules) is True


def test_sender_substring_over_identity_fields():
    notif = vm.Notification.model_validate(
        {"timestamp": "2025-01-01T00:00:00", "source": "whatsapp", "type": "message", "contact_name": "Alice Smith", "interrupt": False}
    )
    assert npn.should_interrupt(notif, [_rule(sender="alice", action="interrupt")]) is True


def test_keyword_matches_body():
    notif = _notif(body="this is URGENT", interrupt=False)
    assert npn.should_interrupt(notif, [_rule(keyword="urgent", action="interrupt")]) is True


def test_keyword_matches_message_extra_field():
    notif = vm.Notification.model_validate(
        {"timestamp": "2025-01-01T00:00:00", "source": "whatsapp", "type": "message", "message": "ping about taxes", "interrupt": False}
    )
    assert npn.should_interrupt(notif, [_rule(keyword="taxes", action="interrupt")]) is True


def test_keyword_regex_alternation():
    rule = _rule(keyword="invoice|payment", action="interrupt")
    assert npn.should_interrupt(_notif(body="your payment is due", interrupt=False), [rule]) is True
    assert npn.should_interrupt(_notif(body="nothing relevant", interrupt=False), [rule]) is False


def test_keyword_regex_anchor():
    rule = _rule(keyword=r"^\$\d+", action="interrupt")
    assert npn.should_interrupt(_notif(body="$500 received", interrupt=False), [rule]) is True
    # The anchor requires the amount at the start, so a mid-body match does not count.
    assert npn.should_interrupt(_notif(body="received $500", interrupt=False), [rule]) is False


def test_keyword_regex_is_case_insensitive():
    assert npn.should_interrupt(_notif(body="ALERT: down", interrupt=False), [_rule(keyword="alert", action="interrupt")]) is True


def test_invalid_keyword_regex_is_rejected():
    with pytest.raises(pyd.ValidationError):
        _rule(keyword="(unclosed", action="interrupt")


# --- general field predicates (match) ---


def _wa(**fields) -> vm.Notification:
    base = {"timestamp": "2025-01-01T00:00:00", "source": "whatsapp", "type": "message"}
    base.update(fields)
    return vm.Notification.model_validate(base)


def test_match_targets_a_concrete_extra_field():
    # The whole point: pool one group chat by its chat_name, which is neither sender nor body.
    notif = _wa(chat_name="Bride squad", interrupt=True)
    rule = _rule(source="whatsapp", match=[{"field": "chat_name", "value": "bride squad"}], action="pool")
    assert npn.should_interrupt(notif, [rule]) is False


def test_match_concrete_field_is_substring_and_case_insensitive():
    notif = _wa(chat_name="The Bride Squad 2024", interrupt=True)
    rule = _rule(match=[{"field": "chat_name", "value": "bride squad"}], action="pool")
    assert npn.should_interrupt(notif, [rule]) is False


def test_match_does_not_apply_when_field_absent():
    # A 1:1 message has no chat_name; the group rule must not touch it.
    notif = _wa(contact_name="Alice", interrupt=True)
    rule = _rule(match=[{"field": "chat_name", "value": "bride squad"}], action="pool")
    assert npn.should_interrupt(notif, [rule]) is True


def test_match_regex_op_on_concrete_field():
    rule = _rule(match=[{"field": "chat_name", "op": "regex", "value": "^proj-"}], action="pool")
    assert npn.should_interrupt(_wa(chat_name="proj-vesta", interrupt=True), [rule]) is False
    assert npn.should_interrupt(_wa(chat_name="my proj-vesta", interrupt=True), [rule]) is True


def test_match_negate_inverts():
    # interrupt for everything whose chat_name is NOT the snoozed group.
    rule = _rule(match=[{"field": "chat_name", "value": "bride squad", "negate": True}], action="interrupt")
    assert npn.should_interrupt(_wa(chat_name="Work standup", interrupt=False), [rule]) is True
    assert npn.should_interrupt(_wa(chat_name="Bride squad", interrupt=False), [rule]) is False


def test_match_negate_on_absent_field_counts_as_not_matching():
    # No chat_name -> does not contain "x" -> negated predicate holds.
    rule = _rule(match=[{"field": "chat_name", "value": "x", "negate": True}], action="interrupt")
    assert npn.should_interrupt(_wa(interrupt=False), [rule]) is True


def test_match_coerces_non_string_fields():
    # is_group is a bool; chat targeting by a bool/int field still works via str-coercion.
    notif = _wa(is_group=True, interrupt=True)
    rule = _rule(match=[{"field": "is_group", "value": "true"}], action="pool")
    assert npn.should_interrupt(notif, [rule]) is False


def test_match_predicates_are_anded():
    notif = _wa(chat_name="Bride squad", is_group=True, interrupt=True)
    # Both predicates hold -> pool.
    both = _rule(match=[{"field": "chat_name", "value": "bride"}, {"field": "is_group", "value": "true"}], action="pool")
    assert npn.should_interrupt(notif, [both]) is False
    # One predicate fails -> rule does not apply -> static flag.
    one = _rule(match=[{"field": "chat_name", "value": "bride"}, {"field": "is_group", "value": "false"}], action="pool")
    assert npn.should_interrupt(notif, [one]) is True


def test_match_sender_alias_searches_identity_fields():
    notif = _wa(contact_name="Alice Smith", interrupt=False)
    rule = _rule(match=[{"field": "sender", "value": "alice"}], action="interrupt")
    assert npn.should_interrupt(notif, [rule]) is True


def test_match_text_alias_searches_body_and_message():
    rule = _rule(match=[{"field": "text", "op": "regex", "value": "taxes"}], action="interrupt")
    assert npn.should_interrupt(_wa(message="ping about taxes", interrupt=False), [rule]) is True
    assert npn.should_interrupt(_notif(body="taxes due", interrupt=False), [rule]) is True


def test_match_invalid_regex_predicate_is_rejected():
    with pytest.raises(pyd.ValidationError):
        _rule(match=[{"field": "chat_name", "op": "regex", "value": "(unclosed"}], action="pool")


def test_match_blank_field_is_rejected():
    with pytest.raises(pyd.ValidationError):
        _rule(match=[{"field": "  ", "value": "x"}], action="pool")


def test_match_predicate_forbids_unknown_keys():
    with pytest.raises(pyd.ValidationError):
        _rule(match=[{"field": "chat_name", "value": "x", "bogus": 1}], action="pool")


# --- legacy sender/keyword normalization into match ---


def test_legacy_sender_keyword_normalize_into_match():
    rule = _rule(source="whatsapp", sender="wife", keyword="urgent", action="interrupt")
    assert rule.match == [
        npn.FieldPredicate(field="sender", op="contains", value="wife"),
        npn.FieldPredicate(field="text", op="regex", value="urgent"),
    ]


def test_legacy_null_sender_keyword_are_dropped_not_predicates():
    # The pre-update CLI wrote sender/keyword as explicit null on every rule; they must vanish, not
    # become predicates that match everything.
    rule = npn.NotificationInterruptRule.model_validate(
        {"id": "x", "source": "twitter", "type": None, "sender": None, "keyword": None, "action": "pool"}
    )
    assert rule.match == []


def test_legacy_rule_on_disk_converges_to_canonical_shape_on_save(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    _write_policy(config, {"rules": [{"id": "a", "source": "whatsapp", "sender": "wife", "keyword": None, "action": "interrupt"}]})
    loaded = npn.load_rules(config)
    assert loaded[0].match == [npn.FieldPredicate(field="sender", op="contains", value="wife")]
    npn.save_rules(loaded, config)
    on_disk = json.loads(npn.policy_path(config).read_text())["rules"][0]
    assert "sender" not in on_disk and "keyword" not in on_disk
    assert on_disk["match"] == [{"field": "sender", "op": "contains", "value": "wife", "negate": False}]


# --- default overrides ---


def _default(**fields) -> npn.NotificationDefault:
    return npn.NotificationDefault(**fields)


def test_default_override_flips_static_when_no_rule_matches():
    notif = _notif(source="outlook", type="message", interrupt=True)
    defaults = [_default(source="outlook", type="message", action="pool")]
    assert npn.should_interrupt(notif, [], defaults) is False


def test_rule_beats_default_override():
    notif = _notif(source="outlook", type="message", interrupt=True)
    rules = [_rule(source="outlook", action="interrupt")]
    defaults = [_default(source="outlook", type="message", action="pool")]
    # The rule matches first, so the override never applies.
    assert npn.should_interrupt(notif, rules, defaults) is True


def test_default_override_matches_source_type_case_insensitively():
    notif = _notif(source="Outlook", type="Message", interrupt=True)
    assert npn.should_interrupt(notif, [], [_default(source="outlook", type="message", action="pool")]) is False


def test_default_override_does_not_apply_to_other_types():
    notif = _notif(source="outlook", type="calendar", interrupt=True)
    # The override targets (outlook, message); a calendar notification falls through to its static flag.
    assert npn.should_interrupt(notif, [], [_default(source="outlook", type="message", action="pool")]) is True


def test_default_override_rejects_core_source():
    with pytest.raises(pyd.ValidationError):
        _default(source="core", action="pool")


def test_save_then_load_defaults_round_trip(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    npn.save_defaults([_default(source="outlook", type="message", action="pool")], config)
    loaded = npn.load_defaults(config)
    assert len(loaded) == 1
    assert loaded[0].source == "outlook"
    assert loaded[0].type == "message"
    assert loaded[0].action == "pool"


def test_rules_and_defaults_share_one_file_without_clobbering(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    npn.save_rules([_rule(source="twitter", action="pool")], config)
    npn.save_defaults([_default(source="outlook", action="pool")], config)
    # Both sections live in the one notification_policy.json; writing one must preserve the other.
    assert len(npn.load_rules(config)) == 1
    assert len(npn.load_defaults(config)) == 1
    npn.save_rules([_rule(source="x", action="interrupt"), _rule(source="y", action="pool")], config)
    assert len(npn.load_rules(config)) == 2
    assert len(npn.load_defaults(config)) == 1
    assert npn.policy_path(config).exists()


def test_first_matching_rule_wins():
    notif = _notif(source="twitter", interrupt=False)
    rules = [_rule(source="twitter", action="interrupt"), _rule(source="twitter", action="pool")]
    assert npn.should_interrupt(notif, rules) is True


def test_empty_conditions_rule_is_catch_all():
    notif = _notif(interrupt=True)
    assert npn.should_interrupt(notif, [_rule(action="pool")]) is False


def test_core_source_is_exempt_and_honors_static_flag():
    notif = _notif(source="core", interrupt=True)
    # A catch-all pool rule must NOT suppress a core notification.
    assert npn.should_interrupt(notif, [_rule(action="pool")]) is True


# --- store: load / save ---


def test_load_missing_file_returns_empty(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    assert npn.load_rules(config) == []


def _write_policy(config, policy):
    npn.policy_path(config).parent.mkdir(parents=True, exist_ok=True)
    npn.policy_path(config).write_text(json.dumps(policy))


def test_load_corrupt_file_returns_empty(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    npn.policy_path(config).parent.mkdir(parents=True, exist_ok=True)
    npn.policy_path(config).write_text("not json")
    assert npn.load_rules(config) == []


def test_load_non_object_file_returns_empty(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    _write_policy(config, ["not", "an", "object"])
    assert npn.load_rules(config) == []


def test_load_drops_invalid_rule_keeps_the_rest(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    # The middle rule carries an unknown field (the model forbids extras), as a newer skill version
    # could write. It must be dropped without taking the surrounding valid rules down with it.
    _write_policy(
        config,
        {
            "rules": [
                {"id": "a", "source": "twitter", "action": "pool"},
                {"id": "b", "source": "whatsapp", "action": "interrupt", "unknown_field": "x"},
                {"id": "c", "type": "dm", "action": "interrupt"},
            ]
        },
    )
    assert [rule.id for rule in npn.load_rules(config)] == ["a", "c"]


def test_load_non_list_section_returns_empty(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    _write_policy(config, {"rules": {"not": "a list"}})
    assert npn.load_rules(config) == []


def test_save_then_load_round_trip(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    saved = npn.save_rules([_rule(source="twitter", action="pool")], config)
    loaded = npn.load_rules(config)
    assert len(loaded) == 1
    assert loaded[0].source == "twitter"
    assert loaded[0].action == "pool"
    assert loaded[0].id == saved[0].id


def test_save_assigns_ids_to_id_less_rules(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    saved = npn.save_rules([_rule(source="twitter", action="pool")], config)
    assert saved[0].id != ""


def test_save_preserves_existing_ids(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    saved = npn.save_rules([_rule(id="fixed-id", source="twitter", action="pool")], config)
    assert saved[0].id == "fixed-id"


# --- notif_sender ---


def test_notif_sender_reads_first_identity_field():
    notif = vm.Notification.model_validate(
        {"timestamp": "2025-01-01T00:00:00", "source": "whatsapp", "type": "message", "contact_name": "Alice Smith"}
    )
    assert npn.notif_sender(notif) == "Alice Smith"


def test_notif_sender_handle_field():
    notif = vm.Notification.model_validate({"timestamp": "2025-01-01T00:00:00", "source": "twitter", "type": "tweet", "handle": "@bob"})
    assert npn.notif_sender(notif) == "@bob"


def test_notif_sender_none_when_no_identity_field():
    notif = vm.Notification.model_validate({"timestamp": "2025-01-01T00:00:00", "source": "twitter", "type": "tweet"})
    assert npn.notif_sender(notif) is None


# --- notif_facet_fields (discoverability) ---


def test_notif_facet_fields_surfaces_structured_extras():
    notif = vm.Notification.model_validate(
        {
            "timestamp": "2025-01-01T00:00:00",
            "source": "whatsapp",
            "type": "message",
            "contact_name": "Alice",  # identity -> excluded (surfaced as `sender`)
            "message": "hello there",  # text -> excluded (reachable via keyword)
            "chat_name": "Bride squad",
            "chat_type": "group",
            "is_group": True,  # coerced to "True"
        }
    )
    assert npn.notif_facet_fields(notif) == {"chat_name": "Bride squad", "chat_type": "group", "is_group": "True"}


def test_notif_facet_fields_skips_overlong_values():
    notif = vm.Notification.model_validate(
        {"timestamp": "2025-01-01T00:00:00", "source": "x", "type": "y", "blob": "z" * (npn.FACET_VALUE_MAXLEN + 1), "tag": "ok"}
    )
    fields = npn.notif_facet_fields(notif)
    assert "blob" not in fields and fields["tag"] == "ok"


def test_notif_facet_fields_empty_without_extras():
    assert npn.notif_facet_fields(_notif()) == {}


# --- core source is not targetable by a rule ---


def test_rule_rejects_core_source():
    with pytest.raises(pyd.ValidationError):
        npn.NotificationInterruptRule(source="core", action="pool")


def test_rule_rejects_core_source_case_insensitive():
    with pytest.raises(pyd.ValidationError):
        npn.NotificationInterruptRule(source="Core", action="interrupt")
