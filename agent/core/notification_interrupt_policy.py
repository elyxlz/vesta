"""Arrival-time notification interrupt policy.

A persistent, ordered ruleset decides whether an incoming notification preempts the agent's
current turn (`interrupt`) or waits in the passive pool until the agent is idle (`pool`). Both the
user (PUT /config/notification-policy) and the agent (tools) edit the same list; monitor_loop reads
it each tick, so edits apply live with no restart.

`source="core"` notifications (greetings, migrations, proactive checks, dreamer) are exempt: they
always honor their own static `interrupt` flag, so a broad user rule can't swallow internal
control-flow. When no rule matches, the decision falls back to the user's per-`(source, type)`
default override (if set), then to the notification's static flag — so skills that set
`interrupt=False` keep pooling unless the user changed that source's default.
"""

import datetime as dt
import functools
import json
import pathlib as pl
import re
import typing as tp
import uuid

import pydantic as pyd

from . import logger
from . import config as cfg
from . import models as vm
from . import state_store

POLICY_FILENAME = "notification_policy.json"

# A predicate's `field` is the notification key it reads. Concrete keys (chat_name, chat_type, …) read
# that exact field; an alias here expands to a set of per-source synonyms and matches if ANY of them
# satisfies the op. This is the single place cross-source field-name knowledge lives — a new source's
# new field is targetable by its concrete name with no code change.
_IDENTITY_FIELDS = ("sender", "contact_name", "handle", "from", "author")
_BODY_FIELDS = ("body", "message", "content")
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {"sender": _IDENTITY_FIELDS, "text": _BODY_FIELDS}


def _is_core_source(value: str) -> bool:
    return value.strip().lower() == vm.CORE_SOURCE


@functools.lru_cache(maxsize=256)
def _compiled_regex(pattern: str) -> re.Pattern[str]:
    """Compile a predicate regex once and cache it: monitor_loop re-parses rules every tick, so without
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
        # A regex predicate is rejected at write time (PUT /config and load_rules, which drops the
        # offending rule) so a bad pattern never reaches the matcher.
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
    action: tp.Literal["interrupt", "pool"]

    @pyd.model_validator(mode="before")
    @classmethod
    def _absorb_legacy_match_fields(cls, data: object) -> object:
        # LEGACY(remove-when: no notification_policy.json in the fleet still carries flat sender/keyword
        # keys — every agent rewrites the file in canonical {source,type,match} shape on its next rule
        # edit). Old rules (and the pre-update skill CLI) wrote flat `sender`/`keyword` keys; fold them
        # into `match` predicates so they keep working and extra="forbid" doesn't drop them. `sender` is
        # a case-insensitive substring over the identity alias; `keyword` is a regex over the text alias.
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
        # Core notifications are exempt from rules at evaluation time (see should_interrupt); forbid
        # targeting them here too, so a rule that could never apply can't be created.
        if value is not None and _is_core_source(value):
            raise ValueError(f"cannot target source={vm.CORE_SOURCE!r}: core notifications are never affected by rules")
        return value


class NotificationDefault(pyd.BaseModel):
    """A user override of a source's static interrupt default, keyed by exact (source, type). Consulted
    after the rules (so a specific rule still wins) and before the notification's own static flag, so a
    user can flip e.g. "outlook -> snooze by default" without a catch-all rule. `type=""` is the
    no-type bucket (matches a notification whose type is empty)."""

    model_config = pyd.ConfigDict(extra="forbid")

    source: str
    type: str = ""
    action: tp.Literal["interrupt", "pool"]

    @pyd.field_validator("source")
    @classmethod
    def _reject_core_source(cls, value: str) -> str:
        if _is_core_source(value):
            raise ValueError(f"cannot override source={vm.CORE_SOURCE!r}: core notifications are never affected by rules")
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


def _field_raw(notif: vm.Notification, field: str) -> object | None:
    """The raw value of one notification field (declared or extra), or None if absent. Declared fields
    the matcher can target (`interrupt`/`timestamp` str-coerced so e.g. the static flag is targetable;
    `file_path` is internal and omitted) are read explicitly, then the open `model_extra` keys."""
    declared = {"source": notif.source, "type": notif.type, "body": notif.body, "interrupt": notif.interrupt, "timestamp": notif.timestamp}
    if field in declared:
        return declared[field]
    extra = notif.model_extra
    if extra is not None and field in extra:
        return extra[field]
    return None


def _field_values(notif: vm.Notification, field: str) -> list[str]:
    """The notification's value(s) for a predicate field: one value for a concrete key, or every
    present synonym for an alias. Coerced to strings; absent fields contribute nothing."""
    fields = _FIELD_ALIASES[field] if field in _FIELD_ALIASES else (field,)
    return [v for f in fields if (v := _coerce(_field_raw(notif, f))) is not None]


def _predicate_matches(predicate: FieldPredicate, notif: vm.Notification) -> bool:
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


def notif_facet_fields(notif: vm.Notification) -> dict[str, str]:
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


def notif_sender(notif: vm.Notification) -> str | None:
    """The notification's sender, normalized across the per-source identity fields.

    Sender is not one field: each source attaches its own (`contact_name`, `handle`, ...), which is
    why the `sender` alias searches across all of `_IDENTITY_FIELDS`. This returns the first one
    present (via the same `sender` alias the matcher uses), so the event log and facets have a single
    sender value consistent with how rules match."""
    return next(iter(_field_values(notif, "sender")), None)


def _matches(rule: NotificationInterruptRule, notif: vm.Notification) -> bool:
    if rule.source is not None and rule.source.lower() != notif.source.lower():
        return False
    if rule.type is not None and rule.type.lower() != notif.type.lower():
        return False
    return all(_predicate_matches(predicate, notif) for predicate in rule.match)


def _default_override(notif: vm.Notification, defaults: list[NotificationDefault]) -> tp.Literal["interrupt", "pool"] | None:
    """The user's default override for this notification's exact (source, type), or None."""
    for default in defaults:
        if default.source.lower() == notif.source.lower() and default.type.lower() == notif.type.lower():
            return default.action
    return None


def should_interrupt(notif: vm.Notification, rules: list[NotificationInterruptRule], defaults: list[NotificationDefault] | None = None) -> bool:
    """True -> preempt the agent's current turn; False -> pool until idle.

    Precedence: core notifications are exempt (always their own flag); else the first matching rule
    wins; else the user's default override for this (source, type); else the notification's static flag.
    `defaults` is optional (absent = no overrides = the source's static flag), so callers that don't
    use overrides need not pass it."""
    if notif.source == vm.CORE_SOURCE:
        return notif.interrupt
    for rule in rules:
        if _matches(rule, notif):
            return rule.action == "interrupt"
    override = _default_override(notif, defaults or [])
    if override is not None:
        return override == "interrupt"
    return notif.interrupt


def policy_path(config: cfg.VestaConfig) -> pl.Path:
    return config.data_dir / POLICY_FILENAME


def _read_policy(config: cfg.VestaConfig) -> dict[str, object]:
    """The whole policy file as a dict ({"rules": [...], "defaults": [...]}), or {} if absent/corrupt."""
    path = policy_path(config)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"{POLICY_FILENAME} unreadable ({type(e).__name__}: {e}) — ignoring")
        return {}
    if not isinstance(raw, dict):
        logger.error(f"{POLICY_FILENAME} is not an object ({type(raw).__name__}) — ignoring")
        return {}
    return raw


def _validate_section[M: pyd.BaseModel](policy: dict[str, object], key: str, model_cls: type[M]) -> list[M]:
    """Validate one section's entries independently: one malformed entry (e.g. an unknown field a newer
    skill version wrote, or an invalid keyword regex) is dropped and the rest are kept."""
    raw = policy[key] if key in policy else []
    if not isinstance(raw, list):
        logger.error(f"{POLICY_FILENAME}[{key!r}] is not a list ({type(raw).__name__}) — ignoring")
        return []
    items: list[M] = []
    for item in raw:
        try:
            items.append(model_cls.model_validate(item))
        except pyd.ValidationError as e:
            logger.error(f"dropping invalid {key} entry {item} — keeping the rest ({e})")
    return items


def _write_section(config: cfg.VestaConfig, key: str, value: list[dict[str, object]]) -> None:
    """Replace one section of the policy file, preserving the other (read-modify-write)."""
    policy = _read_policy(config)
    policy[key] = value
    state_store.atomic_write_text(policy_path(config), json.dumps(policy))


def load_rules(config: cfg.VestaConfig) -> list[NotificationInterruptRule]:
    return _validate_section(_read_policy(config), "rules", NotificationInterruptRule)


def save_rules(rules: list[NotificationInterruptRule], config: cfg.VestaConfig) -> list[NotificationInterruptRule]:
    for rule in rules:
        if not rule.id:
            rule.id = uuid.uuid4().hex
    _write_section(config, "rules", [rule.model_dump() for rule in rules])
    return rules


def load_defaults(config: cfg.VestaConfig) -> list[NotificationDefault]:
    return _validate_section(_read_policy(config), "defaults", NotificationDefault)


def load_policy(config: cfg.VestaConfig) -> tuple[list[NotificationInterruptRule], list[NotificationDefault]]:
    """Load both sections from a single read+parse — monitor_loop needs both every tick, so this
    avoids reading and JSON-parsing notification_policy.json twice per tick."""
    policy = _read_policy(config)
    return (
        _validate_section(policy, "rules", NotificationInterruptRule),
        _validate_section(policy, "defaults", NotificationDefault),
    )


def save_defaults(defaults: list[NotificationDefault], config: cfg.VestaConfig) -> list[NotificationDefault]:
    _write_section(config, "defaults", [default.model_dump() for default in defaults])
    return defaults
