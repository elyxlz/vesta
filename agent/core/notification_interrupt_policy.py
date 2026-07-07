"""Arrival-time notification interrupt policy.

An ordered ruleset decides an incoming notification's disposition: preempt the agent's current turn
(`interrupt`), wait in the passive pool until the agent is idle (`pool`), or drop without ever reaching
the agent (`trash`). First matching rule wins; with no match the decision falls back to the
notification's own `interrupt` flag — the default the producing skill ships for its own notifications
(whatsapp/chat interrupt, email/finance pool), so a fresh agent with no rules already behaves sensibly.
A notification is never trashed by default, only by an explicit user rule. The user's rules exist to
override those defaults.
The ruleset lives on the agent config
(`VestaConfig.notification_rules`); both the user (PUT /config) and the agent (the notifications skill,
via the same config API) edit it, and monitor_loop reads it from the config store each tick, so edits
apply live with no restart.

`source="core"` notifications (greetings, migrations, proactive checks, dreamer) are exempt: their
disposition is control-flow owned by loops.py (derived from the type), so a broad user rule can't
swallow it. Rules can't target `source="core"` (rejected at write time here).
"""

import datetime as dt
import functools
import re
import typing as tp

import pydantic as pyd

if tp.TYPE_CHECKING:
    from . import models as vm

# The source string for internal control-flow notifications. Owned here (the module that defines the
# core exemption); models.py re-exports it so `vm.CORE_SOURCE` keeps working.
CORE_SOURCE = "core"

# A predicate's `field` is the notification key it reads. Concrete keys (chat_name, chat_type, …) read
# that exact field; an alias here expands to a set of per-source synonyms and matches if ANY of them
# satisfies the op. This is the single place cross-source field-name knowledge lives — a new source's
# new field is targetable by its concrete name with no code change.
_IDENTITY_FIELDS = ("sender", "contact_name", "handle", "from", "author")
_BODY_FIELDS = ("body", "message", "content")
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {"sender": _IDENTITY_FIELDS, "text": _BODY_FIELDS}


def _is_core_source(value: str) -> bool:
    return value.strip().lower() == CORE_SOURCE


@functools.lru_cache(maxsize=256)
def _compiled_regex(pattern: str) -> re.Pattern[str]:
    """Compile a predicate regex once and cache it: monitor_loop re-reads rules every tick, so without
    the cache the hot path would recompile each pattern per tick. IGNORECASE keeps matching
    case-insensitive (a power user can override inline with (?-i:...))."""
    return re.compile(pattern, re.IGNORECASE)


class FieldPredicate(pyd.BaseModel):
    """One match condition: read `field` (a concrete notification key or an alias from `_FIELD_ALIASES`)
    and test it. `op` is `contains` (case-insensitive substring) or `regex` (case-insensitive re.search).
    `negate` inverts the result, so "field does NOT match". A predicate over a field the notification
    lacks does not match (and so, negated, it does)."""

    model_config = pyd.ConfigDict(extra="forbid")

    field: str
    op: tp.Literal["contains", "regex"] = "contains"
    value: str
    negate: bool = False

    @pyd.field_validator("field")
    @classmethod
    def _reject_blank_field(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("predicate field must be non-empty")
        return value

    @pyd.model_validator(mode="after")
    def _validate_regex(self) -> "FieldPredicate":
        # A regex predicate is rejected at write time (PUT /config and load_notification_rules, which
        # drops the offending rule) so a bad pattern never reaches the matcher.
        if self.op == "regex":
            try:
                re.compile(self.value)
            except re.error as e:
                raise ValueError(f"invalid regex {self.value!r}: {e}") from e
        return self


class NotificationInterruptRule(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="forbid")

    id: str = ""
    source: str | None = None
    type: str | None = None
    match: list[FieldPredicate] = []
    action: tp.Literal["interrupt", "pool", "trash"]

    @pyd.model_validator(mode="before")
    @classmethod
    def _absorb_legacy_match_fields(cls, data: object) -> object:
        # LEGACY(remove-when: no stored rule still carries flat sender/keyword keys — every agent
        # rewrites its rules in canonical {source,type,match} shape on its next rule edit). Old rules
        # (from notification_policy.json / the pre-update skill) wrote flat `sender`/`keyword` keys; fold
        # them into `match` predicates so they keep working and extra="forbid" doesn't drop them. `sender`
        # is a case-insensitive substring over the identity alias; `keyword` is a regex over the text alias.
        if not isinstance(data, dict) or not ("sender" in data or "keyword" in data):
            return data
        data = dict(data)
        legacy: list[dict[str, object]] = []
        if "sender" in data:
            sender = data["sender"]
            del data["sender"]
            if sender is not None:
                legacy.append({"field": "sender", "op": "contains", "value": sender})
        if "keyword" in data:
            keyword = data["keyword"]
            del data["keyword"]
            if keyword is not None:
                legacy.append({"field": "text", "op": "regex", "value": keyword})
        existing = data["match"] if "match" in data and data["match"] is not None else []
        data["match"] = legacy + list(existing)
        return data

    @pyd.field_validator("source")
    @classmethod
    def _reject_core_source(cls, value: str | None) -> str | None:
        # Core notifications are exempt from rules (their disposition is owned by loops.py); forbid
        # targeting them here too, so a rule that could never apply can't be created.
        if value is not None and _is_core_source(value):
            raise ValueError(f"cannot target source={CORE_SOURCE!r}: core notifications are never affected by rules")
        return value


def _coerce(value: object) -> str | None:
    """Render a notification field value as a string for matching, or None if absent. Datetimes drop
    microseconds (matching how format_for_display renders them); everything else is str()'d, so bools
    and ints (`is_group`, `chat_id`) are matchable too."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.replace(microsecond=0).isoformat()
    return str(value)


def _field_raw(notif: "vm.Notification", field: str) -> object | None:
    """The raw value of one notification field (declared or extra), or None if absent. Declared fields
    the matcher can target (`timestamp` str-coerced; `file_path` is internal and omitted) are read
    explicitly, then the open `model_extra` keys."""
    declared = {"source": notif.source, "type": notif.type, "body": notif.body, "timestamp": notif.timestamp}
    if field in declared:
        return declared[field]
    extra = notif.model_extra
    if extra is not None and field in extra:
        return extra[field]
    return None


def _field_values(notif: "vm.Notification", field: str) -> list[str]:
    """The notification's value(s) for a predicate field: one value for a concrete key, or every
    present synonym for an alias. Coerced to strings; absent fields contribute nothing."""
    fields = _FIELD_ALIASES[field] if field in _FIELD_ALIASES else (field,)
    return [v for f in fields if (v := _coerce(_field_raw(notif, f))) is not None]


def _predicate_matches(predicate: FieldPredicate, notif: "vm.Notification") -> bool:
    values = _field_values(notif, predicate.field)
    if predicate.op == "contains":
        needle = predicate.value.lower()
        hit = any(needle in v.lower() for v in values)
    else:
        pattern = _compiled_regex(predicate.value)
        hit = any(pattern.search(v) for v in values)
    return hit != predicate.negate


# Extra keys NOT surfaced as discoverable facet fields: the identity fields (already surfaced as the
# single `sender` facet), the free-text fields (reachable via the `text` alias / keyword, and too long
# / private to list), and internals. Everything else scalar is a targetable structured attribute
# (chat_name, chat_type, is_group, media_type, …).
_FACET_EXCLUDE = frozenset({*_IDENTITY_FIELDS, *_BODY_FIELDS, "file_path"})
# Skip a value too long to be a sane rule target (a pasted blob, a long quoted reply); keeps the facet
# map and the event row small.
FACET_VALUE_MAXLEN = 80


def notif_facet_fields(notif: "vm.Notification") -> dict[str, str]:
    """The notification's targetable structured extras, as {field: value} — what the rule editor and the
    skill's `facets` surface so an author can discover fields like `chat_name` to match on. Scalars only,
    string-coerced; identity/text/internal keys are excluded (see `_FACET_EXCLUDE`)."""
    extra = notif.model_extra
    if extra is None:
        return {}
    fields: dict[str, str] = {}
    for key, raw in extra.items():
        if key in _FACET_EXCLUDE:
            continue
        # Scalars only: a list/dict extra would str() to a Python repr ("['a', 'b']"), a nonsense rule
        # target. str/bool/int/float/datetime render to a real matchable token; anything else is skipped.
        if not isinstance(raw, (str, bool, int, float, dt.datetime)):
            continue
        value = _coerce(raw)
        if value is not None and value != "" and len(value) <= FACET_VALUE_MAXLEN:
            fields[key] = value
    return fields


def notif_sender(notif: "vm.Notification") -> str | None:
    """The notification's sender, normalized across the per-source identity fields.

    Sender is not one field: each source attaches its own (`contact_name`, `handle`, ...), which is
    why the `sender` alias searches across all of `_IDENTITY_FIELDS`. This returns the first one
    present (via the same `sender` alias the matcher uses), so the event log and facets have a single
    sender value consistent with how rules match."""
    return next(iter(_field_values(notif, "sender")), None)


def _matches(rule: NotificationInterruptRule, notif: "vm.Notification") -> bool:
    if rule.source is not None and rule.source.lower() != notif.source.lower():
        return False
    if rule.type is not None and rule.type.lower() != notif.type.lower():
        return False
    return all(_predicate_matches(predicate, notif) for predicate in rule.match)


def notif_disposition(notif: "vm.Notification", rules: list[NotificationInterruptRule]) -> tp.Literal["interrupt", "pool", "trash"]:
    """The effective disposition for an arriving notification: `interrupt` (preempt the current turn now),
    `pool` (wait for the idle triage pass), or `trash` (drop without ever reaching the agent).

    First matching rule wins and supplies its action; with no match the notification's own `interrupt`
    flag (the producing skill's default) decides interrupt-vs-pool. A notification is never trashed by
    default, only by an explicit user rule. Core notifications never reach here: loops.py decides their
    disposition from the type."""
    for rule in rules:
        if _matches(rule, notif):
            return rule.action
    return "interrupt" if notif.interrupt else "pool"
