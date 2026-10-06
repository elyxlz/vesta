"""Directions RPC: build the replayable request and parse the route.

The request rides captured `pb` templates: `directions_pb.txt` (driving/walking/bicycling, a
coordinate + mode-flag template) and `transit_pb.txt` (transit, which also carries a time-block
slot). Google does not validate the session token in these `pb`s, so the templates carry a fixed
placeholder; only the coordinates, the mode flag, and the transit time vary.

Transit departure/arrival is set by a `!19m3!1e<0|1>!2e2!3j<epoch>` block (1e0 = depart at,
1e1 = arrive by) placed before the transit-options block. Recapture the templates the way `pb.py`
describes for search when the shape drifts.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from .models import DirectionsLeg, Step
from .pb import json_strings, strip_envelope

_DIR_TEMPLATE = Path(__file__).with_name("directions_pb.txt")
_TRANSIT_TEMPLATE = Path(__file__).with_name("transit_pb.txt")
MODE_FLAG = {"driving": "1e0", "bicycling": "1e1", "walking": "1e2", "transit": "1e3"}

_DUR_TEXT_RE = re.compile(r"^\d+\s*(?:hr|h|min)(?:\s*\d+\s*min)?$")
_DIST_TEXT_RE = re.compile(r"^[\d.,]+\s*(?:km|m|mi)$")
_STEP_RE = re.compile(r"^(?:Head|Turn|Continue|Take|Keep|Merge|Exit|Walk|Board|Get off|Ride|Destination|Slight|Sharp|Roundabout|At )")
_TRANSIT_RE = re.compile(r"^(?:Bus|Subway|Underground|Train|Tram|Light rail|DLR|Overground|Metro|Rail)$")


def transit_time_block(kind: str | None, epoch: int | None) -> str:
    """The transit time block: empty for 'leave now', else depart-at / arrive-by at `epoch`."""
    if kind is None or epoch is None:
        return ""
    if kind not in ("depart", "arrive"):
        raise ValueError(f"time kind must be 'depart' or 'arrive', got {kind!r}")
    flag = "1e0" if kind == "depart" else "1e1"
    return f"!19m3!{flag}!2e2!3j{epoch}"


def build_pb(
    origin: tuple[float, float],
    dest: tuple[float, float],
    mode: str,
    *,
    time_kind: str | None = None,
    epoch: int | None = None,
) -> str:
    if mode not in MODE_FLAG:
        raise ValueError(f"unknown travel mode: {mode!r}")
    coords = {"{OLAT}": str(origin[0]), "{OLNG}": str(origin[1]), "{DLAT}": str(dest[0]), "{DLNG}": str(dest[1])}
    if mode == "transit":
        template = _TRANSIT_TEMPLATE.read_text(encoding="utf-8").strip().replace("{TIME_BLOCK}", transit_time_block(time_kind, epoch))
    else:
        template = _DIR_TEMPLATE.read_text(encoding="utf-8").strip().replace("{MODE}", MODE_FLAG[mode])
    for slot, value in coords.items():
        template = template.replace(slot, value)
    return template


def _clean(text: str) -> str:
    return re.sub(r"</?b>", "", text).replace("\u202f", " ").strip()


def _at(node: object, *path: int) -> object:
    """`node[a][b]...`, or None where the positional array is shorter or not a list."""
    for index in path:
        if not isinstance(node, list) or index >= len(node):
            return None
        node = node[index]
    return node


def _str(node: object, *path: int) -> str | None:
    value = _at(node, *path)
    return _clean(value) if isinstance(value, str) and value.strip() else None


def _step_text(entry: object) -> str | None:
    """A turn step as plain text: the rich-text parts at [14], else the `<step>` HTML at [1] untagged."""
    parts = _at(entry, 14)
    if isinstance(parts, list):
        text = "".join(p for p in (_at(part, 1, 0) for part in parts) if isinstance(p, str))
        if text.strip():
            return _clean(text)
    markup = _at(entry, 1)
    if isinstance(markup, str) and markup:
        return _clean(html.unescape(re.sub(r"<[^>]+>", "", markup))) or None
    return None


def _turn_steps(segment: object) -> list[Step]:
    steps: list[Step] = []
    for item in _at(segment, 1) or []:
        entry = _at(item, 0)
        text = _step_text(entry)
        if text:
            steps.append(Step(instruction=text, distance=_str(entry, 2, 1)))
    return steps


def _transit_step(segment: object) -> Step:
    tags = {_at(entry, 0): entry for entry in _at(segment, 0, 14) or [] if isinstance(entry, list)}
    vehicle, line, headsign = _str(tags.get(4), 2, 3), _str(tags.get(5), 1, 0), _str(tags.get(7), 1, 0)
    board, alight = _at(segment, 5, 0), _at(segment, 5, 1)
    from_stop, depart = _str(board, 0), _str(board, 3, 2)
    to_stop, arrive = _str(alight, 0), _str(alight, 2, 2)
    between = _at(segment, 5, 7)
    num_stops = len(between) + 1 if isinstance(between, list) else None
    duration = _str(segment, 0, 3, 1)
    text = "Take " + (" ".join(x for x in (line, vehicle) if x) or "transit")
    if headsign:
        text += f" towards {headsign}"
    if from_stop:
        text += f" from {from_stop}" + (f" ({depart})" if depart else "")
    if to_stop:
        text += f" to {to_stop}" + (f" ({arrive})" if arrive else "")
    extra = ", ".join(x for x in (f"{num_stops} stops" if num_stops else None, duration) if x)
    if extra:
        text += f", {extra}"
    return Step(
        instruction=text,
        line=line,
        vehicle=vehicle,
        headsign=headsign,
        from_stop=from_stop,
        to_stop=to_stop,
        depart=depart,
        arrive=arrive,
        num_stops=num_stops,
        duration=duration,
    )


def _transit_steps(segments: list[object]) -> list[Step]:
    """One step per segment: kind 2 is a walk, kind 3 a transit ride."""
    steps: list[Step] = []
    for i, segment in enumerate(segments):
        kind = _at(segment, 0, 0)
        if kind == 3:
            steps.append(_transit_step(segment))
        elif kind == 2:
            duration, distance = _str(segment, 0, 3, 1), _str(segment, 0, 2, 1)
            target = _str(segments[i + 1], 5, 0, 0) if i + 1 < len(segments) else None
            text = "Walk" + (f" {duration}" if duration else "") + (f" ({distance})" if distance else "")
            steps.append(Step(instruction=text + (f" to {target}" if target else ""), duration=duration, distance=distance))
        else:
            steps.extend(_turn_steps(segment))
    return steps


def _parse_route(data: object, mode: str) -> DirectionsLeg | None:
    """The recommended route: data[0][1][0], summary at [0] (distance [2], duration [3], clock [5],
    fare [11]) and segments at [1][0][1] (header [0], turn steps [1], transit stops [5])."""
    summary = _at(data, 0, 1, 0, 0)
    segments = _at(data, 0, 1, 0, 1, 0, 1)
    if not isinstance(summary, list) or not isinstance(segments, list):
        return None
    leg = DirectionsLeg(mode=mode, duration_text=_str(summary, 3, 1), distance_text=_str(summary, 2, 1))
    if leg.duration_text is None:
        return None
    if mode == "transit":
        leg.steps = _transit_steps(segments)
        leg.depart, leg.arrive, leg.fare = _str(summary, 5, 0, 2), _str(summary, 5, 1, 2), _str(summary, 11, 1)
    else:
        leg.steps = [step for segment in segments for step in _turn_steps(segment)]
    return leg


def _scrape(data: object, mode: str) -> DirectionsLeg:
    """Fallback when the route structure drifts: pattern-match the flat list of strings."""
    strings = json_strings(data)
    duration_text = next((s for s in strings if _DUR_TEXT_RE.match(s)), None)
    distance_text = next((s for s in strings if _DIST_TEXT_RE.match(s)), None)
    steps: list[Step] = [Step(instruction=_clean(s)) for s in strings if _STEP_RE.match(s) and len(s) < 120]
    if mode == "transit":
        line = next((s for s in strings if _TRANSIT_RE.match(s)), None)
        if line is not None:
            steps.insert(0, Step(instruction="transit", vehicle=line))
    return DirectionsLeg(mode=mode, duration_text=duration_text, distance_text=distance_text, steps=steps)


def parse_directions(raw_body: str, mode: str) -> DirectionsLeg:
    data = json.loads(strip_envelope(raw_body))
    return _parse_route(data, mode) or _scrape(data, mode)
