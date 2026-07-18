"""Tests for the notification interrupt policy: matching, the decision, the config-store ruleset, and
core routing in loops."""

import datetime as dt
import json

import pydantic as pyd
import pytest

from core.notification import CORE_SOURCE, Notification, TYPE_PROACTIVE_CHECK
from core import config as cfg
from core import loops
from core import notification_interrupt_policy as npn


def _notif(**fields) -> Notification:
    base = {"timestamp": dt.datetime(2025, 1, 1), "source": "twitter", "type": "tweet"}
    base.update(fields)
    return Notification.model_validate(base)


def _rule(**fields) -> npn.NotificationInterruptRule:
    # `sender`/`keyword` are test-authoring shorthands for the two most common predicates (sender =
    # substring over the identity alias, keyword = regex over the text alias); fold them into `match`
    # here so rule tests stay readable. The rule model itself only accepts canonical `match` predicates.
    match = list(fields.pop("match", []))
    if "sender" in fields:
        match.append({"field": "sender", "op": "contains", "value": fields.pop("sender")})
    if "keyword" in fields:
        match.append({"field": "text", "op": "regex", "value": fields.pop("keyword")})
    if match:
        fields["match"] = match
    return npn.NotificationInterruptRule(**fields)


# --- matching + notif_disposition ---


def test_no_rules_defaults_to_interrupt():
    assert npn.notif_disposition(_notif(), []) == "interrupt"


def test_no_rules_honors_producer_snooze_default():
    # A skill that ships interrupt=False (email, finance) snoozes when no rule matches — the fallback is
    # the producer's default, not an unconditional interrupt.
    assert npn.notif_disposition(_notif(interrupt=False), []) == "snooze"


def test_matching_rule_overrides_producer_snooze_default():
    notif = _notif(source="finance", interrupt=False)
    assert npn.notif_disposition(notif, [_rule(source="finance", action="interrupt")]) == "interrupt"


def test_source_rule_snoozes():
    assert npn.notif_disposition(_notif(), [_rule(source="twitter", action="snooze")]) == "snooze"


def test_source_rule_interrupts():
    assert npn.notif_disposition(_notif(), [_rule(source="twitter", action="interrupt")]) == "interrupt"


def test_source_match_is_case_insensitive():
    notif = _notif(source="Twitter")
    assert npn.notif_disposition(notif, [_rule(source="twitter", action="snooze")]) == "snooze"


def test_type_rule_matches():
    assert npn.notif_disposition(_notif(type="tweet"), [_rule(type="tweet", action="snooze")]) == "snooze"


def test_conditions_are_anded_within_a_rule():
    # source matches but type does not -> rule does not apply -> falls back to the default interrupt.
    notif = _notif(source="twitter", type="dm")
    rules = [_rule(source="twitter", type="tweet", action="snooze")]
    assert npn.notif_disposition(notif, rules) == "interrupt"


def test_sender_substring_over_identity_fields():
    notif = Notification.model_validate(
        {"timestamp": "2025-01-01T00:00:00", "source": "whatsapp", "type": "message", "contact_name": "Alice Smith"}
    )
    # A source rule snoozes whatsapp; a sender rule earlier interrupts alice specifically.
    rules = [_rule(sender="alice", action="interrupt"), _rule(source="whatsapp", action="snooze")]
    assert npn.notif_disposition(notif, rules) == "interrupt"


def test_keyword_matches_body():
    notif = _notif(body="this is URGENT")
    assert npn.notif_disposition(notif, [_rule(source="twitter", action="snooze"), _rule(keyword="urgent", action="interrupt")]) == "snooze"


def test_keyword_matches_message_extra_field():
    notif = Notification.model_validate(
        {"timestamp": "2025-01-01T00:00:00", "source": "whatsapp", "type": "message", "message": "ping about taxes"}
    )
    assert npn.notif_disposition(notif, [_rule(keyword="taxes", action="snooze")]) == "snooze"


def test_keyword_regex_alternation():
    rule = _rule(keyword="invoice|payment", action="snooze")
    assert npn.notif_disposition(_notif(body="your payment is due"), [rule]) == "snooze"
    assert npn.notif_disposition(_notif(body="nothing relevant"), [rule]) == "interrupt"


def test_keyword_regex_anchor():
    rule = _rule(keyword=r"^\$\d+", action="snooze")
    assert npn.notif_disposition(_notif(body="$500 received"), [rule]) == "snooze"
    # The anchor requires the amount at the start, so a mid-body match does not count.
    assert npn.notif_disposition(_notif(body="received $500"), [rule]) == "interrupt"


def test_keyword_regex_is_case_insensitive():
    assert npn.notif_disposition(_notif(body="ALERT: down"), [_rule(keyword="alert", action="snooze")]) == "snooze"


def test_invalid_keyword_regex_is_rejected():
    with pytest.raises(pyd.ValidationError):
        _rule(keyword="(unclosed", action="interrupt")


# --- general field predicates (match) ---


def _wa(**fields) -> Notification:
    base = {"timestamp": "2025-01-01T00:00:00", "source": "whatsapp", "type": "message"}
    base.update(fields)
    return Notification.model_validate(base)


def test_match_targets_a_concrete_extra_field():
    # The whole point: snooze one group chat by its chat_name, which is neither sender nor body.
    notif = _wa(chat_name="Bride squad")
    rule = _rule(source="whatsapp", match=[{"field": "chat_name", "value": "bride squad"}], action="snooze")
    assert npn.notif_disposition(notif, [rule]) == "snooze"


def test_match_concrete_field_is_substring_and_case_insensitive():
    notif = _wa(chat_name="The Bride Squad 2024")
    rule = _rule(match=[{"field": "chat_name", "value": "bride squad"}], action="snooze")
    assert npn.notif_disposition(notif, [rule]) == "snooze"


def test_match_does_not_apply_when_field_absent():
    # A 1:1 message has no chat_name; the group rule must not touch it.
    notif = _wa(contact_name="Alice")
    rule = _rule(match=[{"field": "chat_name", "value": "bride squad"}], action="snooze")
    assert npn.notif_disposition(notif, [rule]) == "interrupt"


def test_match_regex_op_on_concrete_field():
    rule = _rule(match=[{"field": "chat_name", "op": "regex", "value": "^proj-"}], action="snooze")
    assert npn.notif_disposition(_wa(chat_name="proj-vesta"), [rule]) == "snooze"
    assert npn.notif_disposition(_wa(chat_name="my proj-vesta"), [rule]) == "interrupt"


def test_match_negate_inverts():
    # interrupt for everything whose chat_name is NOT the snoozed group; snooze the rest via a later rule.
    rules = [_rule(match=[{"field": "chat_name", "value": "bride squad", "negate": True}], action="interrupt"), _rule(action="snooze")]
    assert npn.notif_disposition(_wa(chat_name="Work standup"), rules) == "interrupt"
    assert npn.notif_disposition(_wa(chat_name="Bride squad"), rules) == "snooze"


def test_match_negate_on_absent_field_counts_as_not_matching():
    # No chat_name -> does not contain "x" -> negated predicate holds.
    rule = _rule(match=[{"field": "chat_name", "value": "x", "negate": True}], action="snooze")
    assert npn.notif_disposition(_wa(), [rule]) == "snooze"


def test_match_coerces_non_string_fields():
    # is_group is a bool; chat targeting by a bool/int field still works via str-coercion.
    notif = _wa(is_group=True)
    rule = _rule(match=[{"field": "is_group", "value": "true"}], action="snooze")
    assert npn.notif_disposition(notif, [rule]) == "snooze"


def test_match_predicates_are_anded():
    notif = _wa(chat_name="Bride squad", is_group=True)
    # Both predicates hold -> snooze.
    both = _rule(match=[{"field": "chat_name", "value": "bride"}, {"field": "is_group", "value": "true"}], action="snooze")
    assert npn.notif_disposition(notif, [both]) == "snooze"
    # One predicate fails -> rule does not apply -> default interrupt.
    one = _rule(match=[{"field": "chat_name", "value": "bride"}, {"field": "is_group", "value": "false"}], action="snooze")
    assert npn.notif_disposition(notif, [one]) == "interrupt"


def test_match_sender_alias_searches_identity_fields():
    notif = _wa(contact_name="Alice Smith")
    rule = _rule(match=[{"field": "sender", "value": "alice"}], action="snooze")
    assert npn.notif_disposition(notif, [rule]) == "snooze"


def test_match_text_alias_searches_body_and_message():
    rule = _rule(match=[{"field": "text", "op": "regex", "value": "taxes"}], action="snooze")
    assert npn.notif_disposition(_wa(message="ping about taxes"), [rule]) == "snooze"
    assert npn.notif_disposition(_notif(body="taxes due"), [rule]) == "snooze"


def test_match_invalid_regex_predicate_is_rejected():
    with pytest.raises(pyd.ValidationError):
        _rule(match=[{"field": "chat_name", "op": "regex", "value": "(unclosed"}], action="snooze")


def test_match_blank_field_is_rejected():
    with pytest.raises(pyd.ValidationError):
        _rule(match=[{"field": "  ", "value": "x"}], action="snooze")


def test_match_predicate_forbids_unknown_keys():
    with pytest.raises(pyd.ValidationError):
        _rule(match=[{"field": "chat_name", "value": "x", "bogus": 1}], action="snooze")


# --- notif_disposition ordering / catch-all ---


def test_first_matching_rule_wins():
    notif = _notif(source="twitter")
    rules = [_rule(source="twitter", action="interrupt"), _rule(source="twitter", action="snooze")]
    assert npn.notif_disposition(notif, rules) == "interrupt"


def test_empty_conditions_rule_is_catch_all():
    assert npn.notif_disposition(_notif(), [_rule(action="snooze")]) == "snooze"


def test_matching_trash_rule_trashes():
    notif = _notif(source="whatsapp", chat_name="status")
    assert (
        npn.notif_disposition(notif, [_rule(source="whatsapp", action="trash", match=[npn.FieldPredicate(field="chat_name", value="status")])])
        == "trash"
    )


def test_never_trashes_without_a_matching_rule():
    # trash is only ever an explicit user rule; the producer default is only ever interrupt/snooze.
    assert npn.notif_disposition(_notif(interrupt=True), []) == "interrupt"
    assert npn.notif_disposition(_notif(interrupt=False), []) == "snooze"


# --- config store: load_notification_rules ---


def _write_rules_store(config, rules):
    config.data_dir.mkdir(parents=True, exist_ok=True)
    (config.data_dir / "config.json").write_text(json.dumps({"notification_rules": rules}))


def test_load_missing_store_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DIR", str(tmp_path / "agent"))
    assert cfg.load_notification_rules() == []


def test_load_drops_invalid_rule_keeps_the_rest(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DIR", str(tmp_path / "agent"))
    config = cfg.VestaConfig()
    # The middle rule carries an unknown field (the model forbids extras). It must be dropped without
    # taking the surrounding valid rules down with it.
    _write_rules_store(
        config,
        [
            {"id": "a", "source": "twitter", "action": "snooze"},
            {"id": "b", "source": "whatsapp", "action": "interrupt", "unknown_field": "x"},
            {"id": "c", "type": "dm", "action": "interrupt"},
        ],
    )
    assert [rule.id for rule in cfg.load_notification_rules()] == ["a", "c"]


def test_load_round_trips_a_written_store(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DIR", str(tmp_path / "agent"))
    config = cfg.VestaConfig()
    _write_rules_store(config, [{"id": "r1", "source": "twitter", "action": "snooze"}])
    loaded = cfg.load_notification_rules()
    assert len(loaded) == 1
    assert loaded[0].id == "r1"
    assert loaded[0].source == "twitter"
    assert loaded[0].action == "snooze"
    # And the loaded rule drives the decision.
    assert npn.notif_disposition(_notif(), loaded) == "snooze"


# --- core routing via loops._notif_disposition ---


def test_core_type_interrupts_despite_catch_all_snooze_rule():
    # A non-snooze core type (migration) preempts even under a broad user snooze rule.
    notif = _notif(source=CORE_SOURCE, type="migration")
    assert loops._notif_disposition(notif, [_rule(action="snooze")]) == "interrupt"


def test_core_snooze_type_snoozes():
    notif = _notif(source=CORE_SOURCE, type=TYPE_PROACTIVE_CHECK)
    assert loops._notif_disposition(notif, []) == "snooze"


def test_non_core_goes_through_rules():
    notif = _notif(source="twitter")
    assert loops._notif_disposition(notif, [_rule(source="twitter", action="snooze")]) == "snooze"
    assert loops._notif_disposition(notif, []) == "interrupt"


def test_core_notification_is_never_trashed():
    # Core disposition is control-flow (type-derived) and exempt from user rules, so a broad trash rule
    # can't drop a core notification.
    notif = _notif(source=CORE_SOURCE, type="migration")
    assert loops._notif_disposition(notif, [_rule(action="trash")]) == "interrupt"


# --- notif_sender ---


def test_notif_sender_reads_first_identity_field():
    notif = Notification.model_validate(
        {"timestamp": "2025-01-01T00:00:00", "source": "whatsapp", "type": "message", "contact_name": "Alice Smith"}
    )
    assert npn.notif_sender(notif) == "Alice Smith"


def test_notif_sender_handle_field():
    notif = Notification.model_validate({"timestamp": "2025-01-01T00:00:00", "source": "twitter", "type": "tweet", "handle": "@bob"})
    assert npn.notif_sender(notif) == "@bob"


def test_notif_sender_none_when_no_identity_field():
    notif = Notification.model_validate({"timestamp": "2025-01-01T00:00:00", "source": "twitter", "type": "tweet"})
    assert npn.notif_sender(notif) is None


# --- notif_facet_fields (discoverability) ---


def test_notif_facet_fields_surfaces_structured_extras():
    notif = Notification.model_validate(
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
    notif = Notification.model_validate(
        {"timestamp": "2025-01-01T00:00:00", "source": "x", "type": "y", "blob": "z" * (npn.FACET_VALUE_MAXLEN + 1), "tag": "ok"}
    )
    fields = npn.notif_facet_fields(notif)
    assert "blob" not in fields and fields["tag"] == "ok"


def test_notif_facet_fields_empty_without_extras():
    assert npn.notif_facet_fields(_notif()) == {}


def test_notif_facet_fields_skips_non_scalar_values():
    # A list/dict extra would str() to a Python repr, not a real rule target, so it must be skipped.
    notif = Notification.model_validate(
        {"timestamp": "2025-01-01T00:00:00", "source": "x", "type": "y", "labels": ["a", "b"], "meta": {"k": "v"}, "tag": "ok"}
    )
    assert npn.notif_facet_fields(notif) == {"tag": "ok"}


# --- core source is not targetable by a rule ---


def test_rule_rejects_core_source():
    with pytest.raises(pyd.ValidationError):
        npn.NotificationInterruptRule(source="core", action="snooze")


def test_rule_rejects_core_source_case_insensitive():
    with pytest.raises(pyd.ValidationError):
        npn.NotificationInterruptRule(source="Core", action="interrupt")
