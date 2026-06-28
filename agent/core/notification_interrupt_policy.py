"""Arrival-time notification interrupt policy.

A persistent, ordered ruleset decides whether an incoming notification preempts the agent's
current turn (`interrupt`) or waits in the passive pool until the agent is idle (`pool`). Both the
user (PUT /config/notification-interrupt-rules) and the agent (tools) edit the same list; monitor_loop reads
it each tick, so edits apply live with no restart.

`source="core"` notifications (greetings, migrations, proactive checks, dreamer) are exempt: they
always honor their own static `interrupt` flag, so a broad user rule can't swallow internal
control-flow. When no rule matches, the decision falls back to the user's per-`(source, type)`
default override (if set), then to the notification's static flag — so skills that set
`interrupt=False` keep pooling unless the user changed that source's default.
"""

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

# `sender` is matched (case-insensitive substring) against whichever of these per-source identity
# fields are present; the field name varies by skill.
_IDENTITY_FIELDS = ("sender", "contact_name", "handle", "from", "author")
# `keyword` is a case-insensitive regex (re.search) matched against `body` (a declared field,
# handled separately) plus these text extras.
_BODY_EXTRA_FIELDS = ("message", "content")


def _is_core_source(value: str) -> bool:
    return value.strip().lower() == vm.CORE_SOURCE


@functools.lru_cache(maxsize=256)
def _compiled_keyword(pattern: str) -> re.Pattern[str]:
    """Compile a keyword regex once and cache it: monitor_loop re-parses rules every tick, so without
    the cache the hot path would recompile each pattern per tick. IGNORECASE keeps matching
    case-insensitive (a power user can override inline with (?-i:...))."""
    return re.compile(pattern, re.IGNORECASE)


class NotificationInterruptRule(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="forbid")

    id: str = ""
    source: str | None = None
    type: str | None = None
    sender: str | None = None
    keyword: str | None = None
    action: tp.Literal["interrupt", "pool"]

    @pyd.field_validator("source")
    @classmethod
    def _reject_core_source(cls, value: str | None) -> str | None:
        # Core notifications are exempt from rules at evaluation time (see should_interrupt); forbid
        # targeting them here too, so a rule that could never apply can't be created.
        if value is not None and _is_core_source(value):
            raise ValueError(f"cannot target source={vm.CORE_SOURCE!r}: core notifications are never affected by rules")
        return value

    @pyd.field_validator("keyword")
    @classmethod
    def _validate_keyword_regex(cls, value: str | None) -> str | None:
        # `keyword` is a regex; reject an invalid pattern at write time (PUT /config and model_validate
        # in load_rules, which drops the offending rule) so a bad pattern never reaches the matcher.
        if value is not None:
            try:
                re.compile(value)
            except re.error as e:
                raise ValueError(f"invalid keyword regex {value!r}: {e}") from e
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


def _extra_str(notif: vm.Notification, field: str) -> str | None:
    extra = notif.model_extra
    if extra is None:
        return None
    if field in extra and isinstance(extra[field], str):
        return extra[field]
    return None


def notif_sender(notif: vm.Notification) -> str | None:
    """The notification's sender, normalized across the per-source identity fields.

    Sender is not one field: each source attaches its own (`contact_name`, `handle`, ...), which is
    why `sender` rule-matching searches across all of `_IDENTITY_FIELDS`. This returns the first one
    present, so the event log and facets have a single sender value consistent with how rules match."""
    for field in _IDENTITY_FIELDS:
        value = _extra_str(notif, field)
        if value is not None:
            return value
    return None


def _matches(rule: NotificationInterruptRule, notif: vm.Notification) -> bool:
    if rule.source is not None and rule.source.lower() != notif.source.lower():
        return False
    if rule.type is not None and rule.type.lower() != notif.type.lower():
        return False
    if rule.sender is not None:
        needle = rule.sender.lower()
        hay = [v.lower() for f in _IDENTITY_FIELDS if (v := _extra_str(notif, f)) is not None]
        if not any(needle in h for h in hay):
            return False
    if rule.keyword is not None:
        pattern = _compiled_keyword(rule.keyword)
        candidates = [v for f in _BODY_EXTRA_FIELDS if (v := _extra_str(notif, f)) is not None]
        if notif.body is not None:
            candidates.append(notif.body)
        if not any(pattern.search(c) for c in candidates):
            return False
    return True


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
