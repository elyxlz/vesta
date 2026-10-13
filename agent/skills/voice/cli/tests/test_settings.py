"""One function checks a key and a value against a schema, for every `set` command and route."""

import pytest
from voice.settings import Domain, SettingDef, SettingValue, check_setting, clamped

SCHEMA: list[SettingDef] = [
    {"key": "flag", "type": "bool", "default": True},
    {"key": "level", "type": "number", "default": 0.8, "min": 0.5, "max": 0.9},
    {"key": "timeout_ms", "type": "number", "default": 5000, "min": 500, "max": 10000},
    {"key": "voice", "type": "select", "default": "a", "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]},
    {"key": "address", "type": "text", "default": "http://127.0.0.1:9000"},
]


@pytest.mark.parametrize(
    ("key", "value", "stored"),
    [
        ("flag", True, True),
        ("flag", "off", False),
        ("flag", "ON", True),
        ("level", 0.7, 0.7),
        ("level", "0.7", 0.7),
        ("timeout_ms", "3000", 3000),
        ("timeout_ms", 3000.0, 3000),
        ("voice", "b", "b"),
        ("address", " http://box:1 ", "http://box:1"),
    ],
)
def test_a_valid_value_is_stored_in_the_type_of_its_setting(key: str, value: SettingValue, stored: SettingValue) -> None:
    result = check_setting(SCHEMA, key, value)

    assert result == stored
    assert type(result) is type(stored)


@pytest.mark.parametrize(
    ("key", "value", "says"),
    [
        ("nope", 1, "unknown setting: nope"),
        ("flag", "maybe", "must be on or off"),
        ("flag", 1, "must be on or off"),
        ("level", "high", "must be a number"),
        ("level", True, "must be a number"),
        ("level", "nan", "must be a number"),
        ("timeout_ms", "nan", "must be a number"),
        ("level", 0.4, "at least 0.5"),
        ("level", 0.95, "at most 0.9"),
        ("timeout_ms", 700.5, "whole number"),
        ("voice", "c", "one of its options"),
        ("address", "", "not empty"),
        ("address", "   ", "not empty"),
        ("address", 5, "not empty"),
    ],
)
def test_a_wrong_key_type_or_range_is_refused(key: str, value: SettingValue, says: str) -> None:
    with pytest.raises(ValueError, match=says):
        check_setting(SCHEMA, key, value)


@pytest.mark.parametrize(
    ("entry", "value"),
    [({"level": 0.7}, 0.7), ({"level": 5}, 0.9), ({"level": 0.1}, 0.5), ({}, 0.8), ({"level": "high"}, 0.8), ({"level": True}, 0.8)],
)
def test_a_provider_reads_a_stored_number_inside_its_range_or_the_default(entry: Domain, value: float) -> None:
    assert clamped(entry, "level", 0.8, 0.5, 0.9) == value
