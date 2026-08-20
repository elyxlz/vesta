"""Pinned positions in Google's place proto.

Every RPC describes a place with the same positional array, the proto: one per result in a
search response and element 6 of the place-detail response. The readers here own the pinned
indexes every parser shares. Opening hours are numeric ([[open_hour, minute?], [close_hour,
minute?]] per interval), so they read the same in every locale; the open-state code is Google's
own answer computed at request time (codes 1 and 2 render as "Open", 4 and 5 as "Closed").
"""

from __future__ import annotations

import re

from .pb import is_web_url

_FTID_RE = re.compile(r"^0x[0-9a-f]+:0x[0-9a-f]+$")
_OPEN_STATES: dict[int, bool] = {1: True, 2: True, 4: False, 5: False}
DAY_MIN = 24 * 60


def _at(node: object, *path: int) -> object | None:
    for index in path:
        if not isinstance(node, list) or not 0 <= index < len(node):
            return None
        node = node[index]
    return node


def is_proto(node: object) -> bool:
    """A place proto: element 10 is the place's ftid and element 11 its name."""
    if not isinstance(node, list) or len(node) <= 11:
        return False
    candidate = node[10]
    return isinstance(candidate, str) and bool(_FTID_RE.match(candidate)) and isinstance(node[11], str)


def ftid(proto: list[object] | None) -> str | None:
    value = _at(proto, 10)
    return value if isinstance(value, str) and _FTID_RE.match(value) else None


def name(proto: list[object] | None) -> str | None:
    value = _at(proto, 11)
    return value if isinstance(value, str) else None


def address(proto: list[object] | None) -> str | None:
    value = _at(proto, 39)
    return value if isinstance(value, str) else None


def coords(proto: list[object] | None) -> tuple[float, float] | None:
    lat, lng = _at(proto, 9, 2), _at(proto, 9, 3)
    if isinstance(lat, int | float) and isinstance(lng, int | float) and not isinstance(lat, bool) and not isinstance(lng, bool):
        return (float(lat), float(lng))
    return None


def rating(proto: list[object] | None) -> float | None:
    value = _at(proto, 4, 7)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def category(proto: list[object] | None) -> str | None:
    value = _at(proto, 13, 0)
    return value if isinstance(value, str) else None


def website(proto: list[object] | None) -> str | None:
    url = _at(proto, 7, 0)
    return url if isinstance(url, str) and is_web_url(url) else None


def _int_at(proto: list[object] | None, *path: int) -> int | None:
    value = _at(proto, *path)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def review_count(proto: list[object] | None) -> int | None:
    return _int_at(proto, 37, 1)


def phone(proto: list[object] | None) -> str | None:
    number = _at(proto, 178, 0, 0)
    return number if isinstance(number, str) else None


def open_now(proto: list[object] | None) -> bool | None:
    state = _int_at(proto, 203, 1, 2)
    if state is None or state not in _OPEN_STATES:
        return None
    return _OPEN_STATES[state]


def open_intervals(proto: list[object] | None) -> list[tuple[int, int]]:
    """Today's opening intervals as minutes since midnight; a close at or before its open wraps
    past midnight, so an end may exceed 1440."""
    entries = _at(proto, 203, 1, 0, 3)
    if not isinstance(entries, list):
        return []
    intervals: list[tuple[int, int]] = []
    for entry in entries:
        opens = _clock_min(_at(entry, 1, 0))
        closes = _clock_min(_at(entry, 1, 1))
        if opens is None or closes is None:
            continue
        intervals.append((opens, closes if closes > opens else closes + DAY_MIN))
    return intervals


def _clock_min(point: object) -> int | None:
    """A clock point [hour, minute?]; an absent or null part means zero ("12 am" is [])."""
    if not isinstance(point, list):
        return None
    hour = point[0] if len(point) >= 1 and isinstance(point[0], int) and not isinstance(point[0], bool) else 0
    minute = point[1] if len(point) >= 2 and isinstance(point[1], int) and not isinstance(point[1], bool) else 0
    return hour * 60 + minute
