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
# Mirrors NotificationInterruptRule: id + optional match fields + required action.
MATCH_FIELDS = ("source", "type", "sender", "keyword")
ACTIONS = ("interrupt", "pool")
# The exact key sets core's pydantic models accept (extra="forbid"): a section written with any other
# shape is silently dropped by core's validator (issue #925). Keep in step with
# NotificationInterruptRule / NotificationDefault in core/notification_interrupt_policy.py.
RULE_KEYS = {"id", *MATCH_FIELDS, "action"}
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


def load_section(key: str) -> list[dict[str, object]]:
    section = _load_policy().get(key, [])
    return section if isinstance(section, list) else []


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
        keyword = item["keyword"] if "keyword" in item else None
        if isinstance(keyword, str):
            re.compile(keyword)


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
    print(_render(load_section("rules")))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    if args.source and args.source.strip().lower() == CORE_SOURCE:
        print(f"error: cannot target source={CORE_SOURCE}; core notifications are never affected by rules", file=sys.stderr)
        return 1
    if args.keyword is not None:
        try:
            re.compile(args.keyword)
        except re.error as e:
            print(f"error: --keyword is a regex and {args.keyword!r} is invalid: {e}", file=sys.stderr)
            return 1
    conditions = {field: getattr(args, field) for field in MATCH_FIELDS if getattr(args, field) is not None}
    rule: dict[str, object] = {"id": uuid.uuid4().hex}
    for field in MATCH_FIELDS:
        rule[field] = conditions[field] if field in conditions else None
    rule["action"] = args.action
    rules = load_section("rules")
    rules.append(rule)
    save_section("rules", rules)
    scope = ", ".join(f"{k}={v}" for k, v in conditions.items()) or "any notification (catch-all)"
    print(f"Added rule {rule['id']}: {scope} -> {args.action}. Now {len(rules)} rule(s); applies next tick.")
    return 0


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


def cmd_set_default(args: argparse.Namespace) -> int:
    if args.source.strip().lower() == CORE_SOURCE:
        print(f"error: cannot override source={CORE_SOURCE}; core notifications are never affected by rules", file=sys.stderr)
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
    """List the source/type/sender values seen in past notifications, so you know what to target.

    Reads the notification history in events.db directly (read-only), mirroring the distinct query
    EventBus would run; keep in step with core/events.py if the stored facet fields change."""
    if not EVENTS_DB.exists():
        print(json.dumps({label: [] for label, _field in FACET_FIELDS}, indent=2))
        return 0
    conn = sqlite3.connect(f"file:{EVENTS_DB}?mode=ro", uri=True)
    try:
        facets = {}
        for label, field in FACET_FIELDS:
            rows = conn.execute(
                f"SELECT json_extract(data, '$.{field}') AS v FROM events "
                "WHERE json_extract(data, '$.type') = 'notification' AND v IS NOT NULL AND v != '' "
                "GROUP BY v ORDER BY MAX(id) DESC LIMIT ?",
                (FACET_LIMIT,),
            ).fetchall()
            facets[label] = [r[0] for r in rows]
    finally:
        conn.close()
    print(json.dumps(facets, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage notification interrupt rules.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Print the current ordered ruleset as JSON.")

    add = sub.add_parser("add", help="Append a rule (first matching rule wins, so order matters).")
    add.add_argument("--action", choices=ACTIONS, required=True, help="interrupt = preempt the current turn; pool = wait until idle.")
    add.add_argument("--source", help="Exact match on notification source (case-insensitive), e.g. twitter, whatsapp.")
    add.add_argument("--type", help="Exact match on notification type (case-insensitive), e.g. message, tweet.")
    add.add_argument("--sender", help="Substring match (case-insensitive) on the sender/contact across identity fields.")
    add.add_argument(
        "--keyword",
        help="Case-insensitive regex (re.search) on the notification body/message, e.g. 'invoice|payment' or '^ALERT'. A plain word still works as a substring.",
    )

    remove = sub.add_parser("remove", help="Remove a rule by id (see `list`).")
    remove.add_argument("id", help="The rule id to remove.")

    sub.add_parser("clear", help="Remove all rules.")

    sub.add_parser("facets", help="List source/type/sender values seen in past notifications (what you can target).")

    sub.add_parser("list-defaults", help="Print the per-(source, type) default overrides as JSON.")

    set_default = sub.add_parser("set-default", help="Override a source's default disposition for a (source, type), used when no rule matches.")
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
