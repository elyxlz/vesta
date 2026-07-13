"""Manage the agent's notification interrupt rules via the config API.

An ordered ruleset routes each incoming notification to 'interrupt' (preempt the agent's current turn),
'snooze' (wait until the agent is idle), or 'trash' (drop it entirely: it never reaches the agent, costs no
turn). First matching rule wins; with no match the notification interrupts. Rules live on the agent
config (VestaConfig.notification_rules) and are read/written through the agent's local HTTP API
(GET/PUT /config), so a change applies on the next monitor tick with no restart. `facets` reads the
notification history (events.db) directly to show what values you can target.
"""

import argparse
import json
import os
import pathlib
import re
import sqlite3
import sys
import urllib.error
import urllib.request
import uuid

ACTIONS = ("interrupt", "snooze", "trash")
OPS = ("contains", "regex")
CORE_SOURCE = "core"
# Facet label -> the field stored on the NotificationEvent in events.db (see core/events.py).
FACET_FIELDS = (("source", "source"), ("type", "notif_type"), ("sender", "sender"))
FACET_LIMIT = 50
EVENTS_DB = pathlib.Path.home() / "agent" / "data" / "events.db"
_REQUEST_TIMEOUT_S = 10


class ApiError(Exception):
    """The agent config API was unreachable or rejected the request."""


def _config_request(method: str, body: dict[str, object] | None = None) -> dict[str, object]:
    """One request to the agent's local config API (127.0.0.1:$WS_PORT/config), authenticated with the
    agent token. Returns the parsed JSON body (or {} when empty)."""
    port = os.environ["WS_PORT"] if "WS_PORT" in os.environ else ""
    if not port:
        raise ApiError("WS_PORT is not set; run this inside the agent container")
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"http://127.0.0.1:{port}/config", data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if "AGENT_TOKEN" in os.environ and os.environ["AGENT_TOKEN"]:
        request.add_header("X-Agent-Token", os.environ["AGENT_TOKEN"])
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_S) as response:
            raw = response.read().decode()
    except urllib.error.HTTPError as e:
        raise ApiError(f"config API {method} failed ({e.code}): {e.read().decode(errors='replace')}") from e
    except urllib.error.URLError as e:
        raise ApiError(f"could not reach the agent config API: {e.reason}") from e
    return json.loads(raw) if raw else {}


def get_rules() -> list[dict[str, object]]:
    config = _config_request("GET")
    rules = config["notification_rules"] if "notification_rules" in config else []
    return rules if isinstance(rules, list) else []


def put_rules(rules: list[dict[str, object]]) -> None:
    _config_request("PUT", {"notification_rules": rules})


def _predicate(field: str, op: str, value: str, negate: bool = False) -> dict[str, object]:
    """The canonical match-predicate shape core's FieldPredicate accepts. One builder so the sender/text
    alias predicates and parsed --match predicates can't drift in shape."""
    return {"field": field, "op": op, "value": value, "negate": negate}


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
    return _predicate(field, op, value, opsym.startswith("!"))


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


def _describe_scope(rule: dict[str, object]) -> str:
    parts = [f"{field}={rule[field]}" for field in ("source", "type") if rule.get(field) is not None]
    for pred in match if isinstance(match := rule.get("match"), list) else []:
        rel = "matches" if (pred["op"] if "op" in pred else "contains") == "regex" else "contains"
        neg = "not " if pred.get("negate") else ""
        parts.append(f"{pred['field']} {neg}{rel} {pred['value']!r}")
    return ", ".join(parts) or "any notification (catch-all)"


def _render(rules: list[dict[str, object]]) -> str:
    if not rules:
        return "No rules. Every notification interrupts the agent's current turn (the default)."
    return json.dumps(rules, indent=2)


def cmd_list(_: argparse.Namespace) -> int:
    rules = get_rules()
    if rules:
        # Guidance on stderr so stdout stays pure JSON: the list is the priority order. Top = highest
        # priority (first match wins); reorder with `move` or `add --before|--after`.
        print("rules in priority order (first match wins; top = highest priority):", file=sys.stderr)
    print(_render(rules))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    if args.source and args.source.strip().lower() == CORE_SOURCE:
        print(f"error: cannot target source={CORE_SOURCE}; core notifications are never affected by rules", file=sys.stderr)
        return 1
    # --sender / --keyword are ergonomic shortcuts for the common cases; both compile to `match`
    # predicates so the stored shape is uniform (sender = substring over identity fields; keyword =
    # regex over the body/message text).
    predicates: list[dict[str, object]] = []
    if args.sender is not None:
        predicates.append(_predicate("sender", "contains", args.sender))
    if args.keyword is not None:
        try:
            re.compile(args.keyword)
        except re.error as e:
            print(f"error: --keyword is a regex and {args.keyword!r} is invalid: {e}", file=sys.stderr)
            return 1
        predicates.append(_predicate("text", "regex", args.keyword))
    for spec in args.match or []:
        try:
            predicates.append(_parse_match(spec))
        except (ValueError, re.error) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    rule: dict[str, object] = {"id": uuid.uuid4().hex, "source": args.source, "type": args.type, "match": predicates, "action": args.action}
    rules = get_rules()
    try:
        index = _placement_index(rules, rule, args.before, args.after)
    except ValueError as e:
        print(f"error: {e} (run `list` to see rule ids)", file=sys.stderr)
        return 1
    rules.insert(index, rule)
    put_rules(rules)
    where = "" if index == len(rules) - 1 else f" at position {index + 1} of {len(rules)}"
    print(f"Added rule {rule['id']}: {_describe_scope(rule)} -> {args.action}{where}. Now {len(rules)} rule(s); applies next tick.")
    return 0


def cmd_move(args: argparse.Namespace) -> int:
    rules = get_rules()
    try:
        current = _index_of(rules, args.id)
    except ValueError as e:
        print(f"error: {e} (run `list` to see rule ids)", file=sys.stderr)
        return 1
    # Pull the rule out first, then resolve --before/--after against the remaining list.
    rule = rules.pop(current)
    try:
        if args.to_top:
            target = 0
        elif args.to_bottom:
            target = len(rules)
        elif args.before is not None:
            target = _index_of(rules, args.before)
        else:
            target = _index_of(rules, args.after) + 1
    except ValueError as e:
        print(f"error: {e} (run `list` to see rule ids)", file=sys.stderr)
        return 1
    rules.insert(target, rule)
    put_rules(rules)
    print(f"Moved rule {args.id} to position {target + 1} of {len(rules)}; applies next tick.")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    rules = get_rules()
    kept = [rule for rule in rules if rule.get("id") != args.id]
    if len(kept) == len(rules):
        print(f"No rule with id {args.id}.", file=sys.stderr)
        return 1
    put_rules(kept)
    print(f"Removed rule {args.id}. Now {len(kept)} rule(s); applies next tick.")
    return 0


def cmd_clear(_: argparse.Namespace) -> int:
    count = len(get_rules())
    put_rules([])
    print(f"Cleared {count} rule(s); applies next tick.")
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
    parser = argparse.ArgumentParser(description="Manage the agent's notification interrupt rules.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Print the current ordered ruleset as JSON.")

    add = sub.add_parser(
        "add",
        help="Add a rule. First matching rule wins (top = highest priority). By default a new rule is "
        "placed above broader rules so a narrow exception is not shadowed; use --before/--after to override.",
    )
    add.add_argument(
        "--action",
        choices=ACTIONS,
        required=True,
        help="interrupt = preempt the current turn; snooze = wait until idle; trash = drop entirely (never reaches you).",
    )
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

    sub.add_parser("facets", help="List source/type/sender + structured field values seen in past notifications (what you can target).")

    args = parser.parse_args()
    handlers = {"list": cmd_list, "add": cmd_add, "move": cmd_move, "remove": cmd_remove, "clear": cmd_clear, "facets": cmd_facets}
    try:
        return handlers[args.command](args)
    except (ValueError, re.error) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ApiError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
