"""The settings schema format, and the one check of a value against a schema.

A provider declares its settings with `settings_schema()`, and the engine declares the behaviors
in the same format, so one check serves every `set` command and every `set` route.
"""

import math
import typing as tp

Scalar = bool | int | float | str
SettingValue = Scalar | list[str] | list[dict[str, str]] | dict[str, dict[str, str]] | dict[str, dict[str, Scalar]]
Domain = dict[str, SettingValue]
# Dynamic JSON a provider hands back as is (a usage report, a subscription).
type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None

BOOL_WORDS: dict[str, bool] = {"on": True, "true": True, "off": False, "false": False}


class SettingOption(tp.TypedDict, total=False):
    value: str
    label: str
    description: str
    preview: str
    custom: bool


class SettingDef(tp.TypedDict, total=False):
    key: str
    type: tp.Literal["bool", "number", "select", "text"]
    label: str
    description: str
    default: bool | int | float | str
    # number:
    min: float
    max: float
    step: float
    unit: str
    # select:
    options: list[SettingOption]


def _check_bool(key: str, value: SettingValue) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in BOOL_WORDS:
        return BOOL_WORDS[value.lower()]
    raise ValueError(f"{key} must be on or off, got {value!r}")


def _check_number(definition: SettingDef, value: SettingValue) -> int | float:
    key = definition["key"]
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(f"{key} must be a number, got {value!r}")
    try:
        number = float(value)
    except ValueError:
        raise ValueError(f"{key} must be a number, got {value!r}") from None
    # `nan` passes every range check, and JSON has no way to write it or `inf`.
    if not math.isfinite(number):
        raise ValueError(f"{key} must be a number, got {value!r}")
    if "min" in definition and number < definition["min"]:
        raise ValueError(f"{key} must be at least {definition['min']}, got {value!r}")
    if "max" in definition and number > definition["max"]:
        raise ValueError(f"{key} must be at most {definition['max']}, got {value!r}")
    # A setting whose default is a whole number stays a whole number (a timeout in ms).
    whole = "default" in definition and isinstance(definition["default"], int) and not isinstance(definition["default"], bool)
    if whole and number != int(number):
        raise ValueError(f"{key} must be a whole number, got {value!r}")
    return int(number) if whole else number


def _check_select(definition: SettingDef, value: SettingValue) -> str:
    key = definition["key"]
    allowed = [option["value"] for option in definition["options"]] if "options" in definition else []
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{key} must be one of its options, got {value!r}")
    return value


def check_setting(schema: list[SettingDef], key: str, value: SettingValue) -> Scalar:
    """The value to store for `key`, or a ValueError that says what is wrong."""
    definition = next((d for d in schema if d["key"] == key), None)
    if definition is None:
        known = ", ".join(d["key"] for d in schema) or "none"
        raise ValueError(f"unknown setting: {key} (settings: {known})")
    kind = definition["type"]
    if kind == "bool":
        return _check_bool(key, value)
    if kind == "number":
        return _check_number(definition, value)
    if kind == "select":
        return _check_select(definition, value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be text that is not empty")
    return value.strip()


def clamped(entry: Domain, key: str, default: float, low: float, high: float) -> float:
    """A stored number held inside the range its provider accepts, or the default when the entry
    has no number there. A provider reads a tuning value through this."""
    value = entry[key] if key in entry else default
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return max(low, min(high, float(value)))
