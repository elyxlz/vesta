"""Pure itinerary helpers: parse leg durations, order stops, lay out a timeline. No IO.

Composition (fetching place detail and directions) lives in `client.py`; this module holds the
network-free logic so it is unit-tested directly.
"""

from __future__ import annotations

import math
import re

_HMS_RE = re.compile(r"(?:(\d+)\s*(?:h|hr))?\s*(?:(\d+)\s*min)?")


def parse_duration_min(text: str | None) -> int:
    """Minutes from a Google duration string ("15 min", "1 h 5 min", "2 hr")."""
    if text is None:
        return 0
    match = _HMS_RE.match(text.strip())
    if match is None:
        return 0
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    return hours * 60 + minutes


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = (math.radians(v) for v in (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def nearest_neighbour(coords: list[tuple[float, float]]) -> list[int]:
    """Visit order that greedily takes the closest next stop, starting from stop 0."""
    if not coords:
        return []
    unvisited = set(range(1, len(coords)))
    order = [0]
    current = 0
    while unvisited:
        nxt = min(unvisited, key=lambda j: haversine_km(coords[current], coords[j]))
        order.append(nxt)
        unvisited.discard(nxt)
        current = nxt
    return order


def _to_min(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _to_hhmm(total: int) -> str:
    total %= 24 * 60
    return f"{total // 60:02d}:{total % 60:02d}"


def lay_out(leg_minutes: list[int], *, start: str, dwell_min: int, count: int) -> list[tuple[str, str]]:
    """Arrive/leave clock times per stop: dwell at each, then the leg to the next."""
    if len(leg_minutes) != max(count - 1, 0):
        raise ValueError("leg_minutes must have one entry per gap between stops")
    out: list[tuple[str, str]] = []
    clock = _to_min(start)
    for i in range(count):
        arrive = clock
        leave = arrive + dwell_min
        out.append((_to_hhmm(arrive), _to_hhmm(leave)))
        if i < len(leg_minutes):
            clock = leave + leg_minutes[i]
    return out
