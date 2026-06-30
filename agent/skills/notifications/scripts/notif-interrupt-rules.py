#!/usr/bin/env python3
"""Manage the agent's notification policy (notification_policy.json: rules + default overrides).

Standalone, stdlib-only: the agent runs this as a subprocess, so it reads and writes the policy
file directly rather than going through core. The shapes mirror NotificationInterruptRule and
NotificationDefault in agent/core/notification_interrupt_policy.py (which owns matching + the engine
that monitor_loop consults); keep the fields and the action values in step if those models change.

A rule routes an incoming notification to 'interrupt' (preempt the agent's current turn) or 'pool'
(wait until the agent is idle); a default override changes a source's fallback when no rule matches.
Edits take effect on the next monitor tick, no restart.
"""

import argparse
import json
import os
import pathlib
import re
import sqlite3
import sys
import uuid

# Rules and defaults share one file: {"rules": [...], "defaults": [...]}. Keep in step with
# agent/core/notification_interrupt_policy.py (POLICY_FILENAME).
POLICY_PATH = pathlib.Path.home() / "agent" / "data" / "notification_policy.json"
EVENTS_DB = pathlib.Path.home() / "agent" / "data" / "events.db"
ACTIONS = ("interrupt", "pool")
OPS = ("contains", "regex")
# The exact key sets core's pydantic models accept (extra="forbid"): a section written with any other
# shape is silently dropped by core's validator (issue #925). Keep in step with
# NotificationInterruptRule / NotificationDefault / FieldPredicate in
# core/notification_interrupt_policy.py.
RULE_KEYS = {"id", "source", "type", "match", "action"}
PREDICATE_KEYS = {"field", "op", "value", "negate"}
DEFAULT_KEYS = {"source", "type", "action"}
# Mirrors models.CORE_SOURCE: core notifications are exempt from rules, so they can't be targeted.
CORE_SOURCE = "core"
# Facet label -> the field stored on the NotificationEvent in events.db (see core/events.py).
FACET_FIELDS = (("source", "source"), ("type", "notif_type"), ("sender", "sender"))
FACET_LIMIT = 50


def _load_policy() -> dict[str, object]:
    if not POLICY_PATH.exists():
        return {}
    try:
        raw = json.loads(POLICY_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _normalize_rule(rule: dict[str, object]) -> dict[str, object]:
    """Fold a legacy flat `sender`/`keyword` rule into the canonical {source, type, match} shape.

    LEGACY(remove-when: no notification_policy.json in the fleet still carries flat sender/keyword keys
    — every agent rewrites the file in canonical shape on its next rule edit). Old rules (and older
    versions of this script) wrote `sender`/`keyword` keys; mirror core's before-validator so re-saving
    converges to `match` predicates and the new RULE_KEYS guard doesn't reject the agent's own history."""
    if not isinstance(rule, dict) or ("sender" not in rule and "keyword" not in rule):
        return rule
    rule = dict(rule)
    legacy: list[dict[str, object]] = []
    sender = rule.pop("sender", None)
    if sender is not None:
        legacy.append({"field": "sender", "op": "contains", "value": sender, "negate": False})
    keyword = rule.pop("keyword", None)
    if keyword is not None:
        legacy.append({"field": "text", "op": "regex", "value": keyword, "negate": False})
    existing = rule.get("match") or []
    rule["match"] = legacy + (existing if isinstance(existing, list) else [])
    return rule


def load_section(key: str) -> list[dict[str, object]]:
    section = _load_policy().get(key, [])
    if not isinstance(section, list):
        return []
    return [_normalize_rule(item) for item in section] if key == "rules" else section


def _validate_section(key: str, items: list[dict[str, object]]) -> None:
    """Guard the write boundary so the skill can never persist a section core would silently drop
    (issue #925): every entry must have only the keys core accepts, a valid action, a non-core source,
    and (rules) a compilable keyword regex. Raises ValueError/re.error; main() reports and exits 1."""
    allowed = RULE_KEYS if key == "rules" else DEFAULT_KEYS
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"{key} entry is not an object: {item!r}")
        unknown = set(item) - allowed
        if unknown:
            raise ValueError(f"{key} entry has fields core forbids: {sorted(unknown)}")
        action = item["action"] if "action" in item else None
        if action not in ACTIONS:
            raise ValueError(f"{key} entry action must be one of {ACTIONS}")
        source = item["source"] if "source" in item else None
        if isinstance(source, str) and source.strip().lower() == CORE_SOURCE:
            raise ValueError(f"{key} entry cannot target source={CORE_SOURCE}")
        if key == "rules" and "match" in item:
            _validate_match(item["match"])


def _validate_match(match: object) -> None:
    """Guard the `match` predicate list against shapes core's FieldPredicate (extra='forbid') would
    reject: each predicate needs a non-empty `field`, a string `value`, op in OPS, bool `negate`, and a
    compilable pattern when op='regex'."""
    if not isinstance(match, list):
        raise ValueError(f"rule match must be a list, got {type(match).__name__}")
    for pred in match:
        if not isinstance(pred, dict):
            raise ValueError(f"match predicate is not an object: {pred!r}")
        unknown = set(pred) - PREDICATE_KEYS
        if unknown:
            raise ValueError(f"match predicate has fields core forbids: {sorted(unknown)}")
        field = pred["field"] if "field" in pred else None
        if not isinstance(field, str) or not field.strip():
            raise ValueError("match predicate field must be a non-empty string")
        value = pred["value"] if "value" in pred else None
        if not isinstance(value, str):
            raise ValueError("match predicate value must be a string")
        op = pred["op"] if "op" in pred else "contains"
        if op not in OPS:
            raise ValueError(f"match predicate op must be one of {OPS}")
        if "negate" in pred and not isinstance(pred["negate"], bool):
            raise ValueError("match predicate negate must be a boolean")
        if op == "regex":
            re.compile(value)


def save_section(key: str, items: list[dict[str, object]]) -> None:
    # Read-modify-write so replacing one section preserves the other.
    _validate_section(key, items)
    policy = _load_policy()
    policy[key] = items
    POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = POLICY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(policy))
    os.replace(tmp, POLICY_PATH)


def _render(rules: list[dict[str, object]]) -> str:
    if not rules:
        return "No rules. Every notification keeps its own default (most interrupt the agent's current turn)."
    return json.dumps(rules, indent=2)


def cmd_list(_: argparse.Namespace) -> int:
    rules = load_section("rules")
    if rules:
        # Guidance on stderr so stdout stays pure JSON: the list is the priority order. Top = highest
        # priority (first match wins); reorder with `move` or `add --before|--after`.
        print("rules in priority order (first match wins; top = highest priority):", file=sys.stderr)
    print(_render(rules))
    return 0


_MATCH_GRAMMAR = re.compile(r"^(?P<field>[^=!~]+)(?P<op>!?~?=)(?P<value>.*)$", re.DOTALL)


def _parse_match(spec: str) -> dict[str, object]:
    """Parse one --match FIELD<op>VALUE into a predicate. Ops: `=` contains, `~=` regex, `!=` not
    contains, `!~=` not regex. e.g. `chat_name=Bride squad`, `chat_name~=^proj-`, `chat_type!=group`."""
    matched = _MATCH_GRAMMAR.match(spec)
    if matched is None:
        raise ValueError(f"--match must be FIELD=VALUE (=, ~= regex, != not, !~= not-regex): {spec!r}")
    field = matched.group("field").strip()
    if not field:
        raise ValueError(f"--match field is empty: {spec!r}")
    opsym = matched.group("op")
    # Strip surrounding whitespace so `--match 'chat_name= Bride squad'` matches the same as the web
    # (which trims), instead of silently storing a leading-space value that never matches.
    value = matched.group("value").strip()
    op = "regex" if "~" in opsym else "contains"
    if op == "regex":
        re.compile(value)  # surfaces re.error -> reported by main()
    return {"field": field, "op": op, "value": value, "negate": opsym.startswith("!")}


def _specificity(rule: dict[str, object]) -> int:
    """How narrowly a rule matches = its condition count (source, type, and each match predicate). Used
    only to place a new rule; the engine itself is purely first-match-wins, never specificity-ranked."""
    count = sum(1 for field in ("source", "type") if rule.get(field) is not None)
    match = rule.get("match")
    return count + (len(match) if isinstance(match, list) else 0)


def _index_of(rules: list[dict[str, object]], rule_id: str) -> int:
    for index, rule in enumerate(rules):
        if rule.get("id") == rule_id:
            return index
    raise ValueError(f"no rule with id {rule_id}")


def _placement_index(rules: list[dict[str, object]], new_rule: dict[str, object], before: str | None, after: str | None) -> int:
    """Where to insert a new rule. Explicit --before/--after win; otherwise auto-place by specificity:
    above the first existing rule that is strictly broader (fewer conditions), so a narrow exception
    lands ahead of the broad rule it refines instead of being shadowed by it. Touches no other rule."""
    if before is not None:
        return _index_of(rules, before)
    if after is not None:
        return _index_of(rules, after) + 1
    spec = _specificity(new_rule)
    for index, rule in enumerate(rules):
        if _specificity(rule) < spec:
            return index
    return len(rules)


def cmd_add(args: argparse.Namespace) -> int:
    if args.source and args.source.strip().lower() == CORE_SOURCE:
        print(f"error: cannot target source={CORE_SOURCE}; core notifications are never affected by rules", file=sys.stderr)
        return 1
    # --sender / --keyword are ergonomic shortcuts for the common cases; both compile to `match`
    # predicates so the stored shape is uniform (sender = substring over identity fields; keyword =
    # regex over the body/message text).
    predicates: list[dict[str, object]] = []
    if args.sender is not None:
        predicates.append({"field": "sender", "op": "contains", "value": args.sender, "negate": False})
    if args.keyword is not None:
        try:
            re.compile(args.keyword)
        except re.error as e:
            print(f"error: --keyword is a regex and {args.keyword!r} is invalid: {e}", file=sys.stderr)
            return 1
        predicates.append({"field": "text", "op": "regex", "value": args.keyword, "negate": False})
    for spec in args.match or []:
        try:
            predicates.append(_parse_match(spec))
        except (ValueError, re.error) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    rule: dict[str, object] = {"id": uuid.uuid4().hex, "source": args.source, "type": args.type, "match": predicates, "action": args.action}
    rules = load_section("rules")
    try:
        index = _placement_index(rules, rule, args.before, args.after)
    except ValueError as e:
        print(f"error: {e} (run `list` to see rule ids)", file=sys.stderr)
        return 1
    rules.insert(index, rule)
    save_section("rules", rules)
    where = "" if index == len(rules) - 1 else f" at position {index + 1} of {len(rules)}"
    print(f"Added rule {rule['id']}: {_describe_scope(rule)} -> {args.action}{where}. Now {len(rules)} rule(s); applies next tick.")
    return 0


def cmd_move(args: argparse.Namespace) -> int:
    rules = load_section("rules")
    try:
        current = _index_of(rules, args.id)
    except ValueError as e:
        print(f"error: {e} (run `list` to see rule ids)", file=sys.stderr)
        return 1
    rule = rules.pop(current)
    rest = rules  # the list without the moved rule; target ids resolve against this
    try:
        if args.to_top:
            target = 0
        elif args.to_bottom:
            target = len(rest)
        elif args.before is not None:
            target = _index_of(rest, args.before)
        elif args.after is not None:
            target = _index_of(rest, args.after) + 1
        else:
            print("error: move needs one of --before, --after, --top, --bottom", file=sys.stderr)
            return 1
    except ValueError as e:
        print(f"error: {e} (run `list` to see rule ids)", file=sys.stderr)
        return 1
    rest.insert(target, rule)
    save_section("rules", rest)
    print(f"Moved rule {args.id} to position {target + 1} of {len(rest)}; applies next tick.")
    return 0


def _describe_scope(rule: dict[str, object]) -> str:
    parts = [f"{field}={rule[field]}" for field in ("source", "type") if rule.get(field) is not None]
    for pred in rule["match"] if isinstance(rule.get("match"), list) else []:
        rel = "matches" if (pred["op"] if "op" in pred else "contains") == "regex" else "contains"
        neg = "not " if pred.get("negate") else ""
        parts.append(f"{pred['field']} {neg}{rel} {pred['value']!r}")
    return ", ".join(parts) or "any notification (catch-all)"


def cmd_remove(args: argparse.Namespace) -> int:
    rules = load_section("rules")
    kept = [rule for rule in rules if rule.get("id") != args.id]
    if len(kept) == len(rules):
        print(f"No rule with id {args.id}.", file=sys.stderr)
        return 1
    save_section("rules", kept)
    print(f"Removed rule {args.id}. Now {len(kept)} rule(s); applies next tick.")
    return 0


def cmd_clear(_: argparse.Namespace) -> int:
    count = len(load_section("rules"))
    save_section("rules", [])
    print(f"Cleared {count} rule(s); applies next tick.")
    return 0


def _default_key(entry: dict[str, object]) -> tuple[str, str]:
    return (str(entry.get("source") or "").lower(), str(entry.get("type") or "").lower())


def cmd_list_defaults(_: argparse.Namespace) -> int:
    defaults = load_section("defaults")
    print(json.dumps(defaults, indent=2) if defaults else "No default overrides. Each source keeps the default it chose.")
    return 0


def _observed_pairs() -> set[tuple[str, str]]:
    """The (source, type) pairs the agent has actually received (distinct, from events.db), lowercased
    for matching. A default override may only toggle one of these — the agent can't invent a fallback
    for a (source, type) it has never seen (that would just add a row that never fires). Mirrors the
    (source, notif_type) grouping in core's notification_static_defaults."""
    if not EVENTS_DB.exists():
        return set()
    conn = sqlite3.connect(f"file:{EVENTS_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT lower(json_extract(data, '$.source')) AS source, "
            "lower(coalesce(json_extract(data, '$.notif_type'), '')) AS type FROM events "
            "WHERE json_extract(data, '$.type') = 'notification' AND source IS NOT NULL AND source != ''"
        ).fetchall()
    finally:
        conn.close()
    return {(str(source), str(type_ or "")) for source, type_ in rows}


def cmd_set_default(args: argparse.Namespace) -> int:
    if args.source.strip().lower() == CORE_SOURCE:
        print(f"error: cannot override source={CORE_SOURCE}; core notifications are never affected by rules", file=sys.stderr)
        return 1
    # Toggle-only: refuse to create a fallback for a (source, type) never received, so the agent can't
    # add phantom rows (e.g. app-chat with no type when every app-chat notification has type=message).
    if (args.source.strip().lower(), args.type.strip().lower()) not in _observed_pairs():
        scope = f"{args.source}/{args.type}" if args.type else args.source
        print(
            f"error: no notifications received for {scope}; you can only change the default of a "
            f"(source, type) the agent has actually seen. Run `facets` to list them.",
            file=sys.stderr,
        )
        return 1
    entry = {"source": args.source, "type": args.type, "action": args.action}
    # Replace any existing override for this exact (source, type), then add the new one.
    defaults = [d for d in load_section("defaults") if _default_key(d) != _default_key(entry)]
    defaults.append(entry)
    save_section("defaults", defaults)
    scope = f"{args.source}/{args.type}" if args.type else args.source
    print(f"Set default for {scope} -> {args.action}. Now {len(defaults)} override(s); applies next tick.")
    return 0


def cmd_clear_default(args: argparse.Namespace) -> int:
    target = {"source": args.source, "type": args.type}
    defaults = load_section("defaults")
    kept = [d for d in defaults if _default_key(d) != _default_key(target)]
    if len(kept) == len(defaults):
        scope = f"{args.source}/{args.type}" if args.type else args.source
        print(f"No default override for {scope}.", file=sys.stderr)
        return 1
    save_section("defaults", kept)
    print(f"Cleared default override; the source's own default applies again. Now {len(kept)} override(s); applies next tick.")
    return 0


def cmd_facets(_: argparse.Namespace) -> int:
    """List the values seen in past notifications, so you know what to target: source/type/sender plus
    every structured extra field (e.g. chat_name, chat_type, is_group) under a `fields` map.

    Reads the notification history in events.db directly (read-only), mirroring the distinct query
    EventBus would run; keep in step with core/events.py if the stored facet fields change."""
    if not EVENTS_DB.exists():
        print(json.dumps({**{label: [] for label, _field in FACET_FIELDS}, "fields": {}}, indent=2))
        return 0
    conn = sqlite3.connect(f"file:{EVENTS_DB}?mode=ro", uri=True)
    try:
        facets: dict[str, object] = {}
        for label, field in FACET_FIELDS:
            rows = conn.execute(
                f"SELECT json_extract(data, '$.{field}') AS v FROM events "
                "WHERE json_extract(data, '$.type') = 'notification' AND v IS NOT NULL AND v != '' "
                "GROUP BY v ORDER BY MAX(id) DESC LIMIT ?",
                (FACET_LIMIT,),
            ).fetchall()
            facets[label] = [r[0] for r in rows]
        # The open set: each distinct (field, value) from the per-notification `fields` map, grouped by
        # field name. json_each walks the map's keys so a new source's new field needs no code change.
        field_rows = conn.execute(
            "SELECT je.key AS field, je.value AS value FROM events, json_each(json_extract(data, '$.fields')) AS je "
            "WHERE json_extract(data, '$.type') = 'notification' AND je.value IS NOT NULL AND je.value != '' "
            "GROUP BY je.key, je.value ORDER BY MAX(events.id) DESC"
        ).fetchall()
        fields: dict[str, list[str]] = {}
        for field, value in field_rows:
            bucket = fields.setdefault(str(field), [])
            if len(bucket) < FACET_LIMIT:
                bucket.append(str(value))
        facets["fields"] = fields
    finally:
        conn.close()
    print(json.dumps(facets, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage notification interrupt rules.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Print the current ordered ruleset as JSON.")

    add = sub.add_parser(
        "add",
        help="Add a rule. First matching rule wins (top = highest priority). By default a new rule is "
        "placed above broader rules so a narrow exception is not shadowed; use --before/--after to override.",
    )
    add.add_argument("--action", choices=ACTIONS, required=True, help="interrupt = preempt the current turn; pool = wait until idle.")
    add.add_argument("--source", help="Exact match on notification source (case-insensitive), e.g. twitter, whatsapp.")
    add.add_argument("--type", help="Exact match on notification type (case-insensitive), e.g. message, tweet.")
    add.add_argument("--sender", help="Shortcut: substring match (case-insensitive) on the sender/contact across identity fields.")
    add.add_argument(
        "--keyword",
        help="Shortcut: case-insensitive regex (re.search) on the notification body/message, e.g. 'invoice|payment' or '^ALERT'. A plain word still works as a substring.",
    )
    add.add_argument(
        "--match",
        action="append",
        metavar="FIELD<op>VALUE",
        help="Match ANY notification field (run `facets` to see them). Ops: '=' substring, '~=' regex, "
        "'!=' not, '!~=' not-regex. Repeatable (all must match). e.g. --match 'chat_name=Bride squad', "
        "--match 'chat_type!=group', --match 'chat_name~=^proj-'. Case-insensitive.",
    )
    add_pos = add.add_mutually_exclusive_group()
    add_pos.add_argument("--before", metavar="ID", help="Place the new rule directly above this rule id (higher priority).")
    add_pos.add_argument("--after", metavar="ID", help="Place the new rule directly below this rule id (lower priority).")

    move = sub.add_parser("move", help="Reorder a rule (first match wins, so position is priority).")
    move.add_argument("id", help="The rule id to move (see `list`).")
    move_to = move.add_mutually_exclusive_group(required=True)
    move_to.add_argument("--before", metavar="ID", help="Move directly above this rule id.")
    move_to.add_argument("--after", metavar="ID", help="Move directly below this rule id.")
    move_to.add_argument("--top", dest="to_top", action="store_true", help="Move to the top (highest priority).")
    move_to.add_argument("--bottom", dest="to_bottom", action="store_true", help="Move to the bottom (lowest priority).")

    remove = sub.add_parser("remove", help="Remove a rule by id (see `list`).")
    remove.add_argument("id", help="The rule id to remove.")

    sub.add_parser("clear", help="Remove all rules.")

    sub.add_parser("facets", help="List source/type/sender values seen in past notifications (what you can target).")

    sub.add_parser("list-defaults", help="Print the per-(source, type) default overrides as JSON.")

    set_default = sub.add_parser(
        "set-default",
        help="Toggle the default disposition of a (source, type) you've received (see `facets`), used when no rule matches. Can't invent a new (source, type).",
    )
    set_default.add_argument("--source", required=True, help="The notification source, e.g. outlook, twitter.")
    set_default.add_argument(
        "--type", default="", help="The notification type to scope to (omit to target the source's no-type notifications)."
    )
    set_default.add_argument("--action", choices=ACTIONS, required=True, help="interrupt = preempt the current turn; pool = wait until idle.")

    clear_default = sub.add_parser("clear-default", help="Remove a default override so the source's own default applies again.")
    clear_default.add_argument("--source", required=True, help="The notification source.")
    clear_default.add_argument("--type", default="", help="The notification type (must match the override you set).")

    args = parser.parse_args()
    handlers = {
        "list": cmd_list,
        "add": cmd_add,
        "move": cmd_move,
        "remove": cmd_remove,
        "clear": cmd_clear,
        "facets": cmd_facets,
        "list-defaults": cmd_list_defaults,
        "set-default": cmd_set_default,
        "clear-default": cmd_clear_default,
    }
    try:
        return handlers[args.command](args)
    except (ValueError, re.error) as e:
        # The write guard refused a section core would drop; report instead of corrupting the file.
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
