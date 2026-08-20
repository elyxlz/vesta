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

import json
import re
from pathlib import Path

from .models import DirectionsLeg, Step
from .pb import strip_envelope

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


def _strings(node: object) -> list[str]:
    out: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(node)
    return out


def _clean(text: str) -> str:
    return re.sub(r"</?b>", "", text).strip()


def parse_directions(raw_body: str, mode: str) -> DirectionsLeg:
    data = json.loads(strip_envelope(raw_body))
    strings = _strings(data)
    # The first duration/distance string is the recommended route's total.
    duration_text = next((s for s in strings if _DUR_TEXT_RE.match(s)), None)
    distance_text = next((s for s in strings if _DIST_TEXT_RE.match(s)), None)
    steps: list[Step] = [Step(instruction=_clean(s)) for s in strings if _STEP_RE.match(s) and len(s) < 120]
    if mode == "transit":
        # The vehicle/line word, best-effort. Clock times in the response are not reliably the
        # route's own departure/arrival, so they are not reported.
        line = next((s for s in strings if _TRANSIT_RE.match(s)), None)
        if line is not None:
            steps.insert(0, Step(instruction="transit", line=line))
    return DirectionsLeg(mode=mode, duration_text=duration_text, distance_text=distance_text, steps=steps)
