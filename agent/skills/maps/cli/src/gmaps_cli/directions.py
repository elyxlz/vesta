"""Directions RPC: build the replayable request and parse the route.

The request rides a captured `pb` template (`directions_pb.txt`) with coordinate slots and a mode
flag. Google does not validate the session token in that `pb`, so the template carries a fixed
placeholder; only the coordinates and the mode flag vary. Recapture the template the way `pb.py`
describes for search when the shape drifts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import DirectionsLeg, Step
from .pb import strip_envelope

_TEMPLATE_PATH = Path(__file__).with_name("directions_pb.txt")
MODE_FLAG = {"driving": "1e0", "bicycling": "1e1", "walking": "1e2", "transit": "1e3"}

_DUR_TEXT_RE = re.compile(r"^\d+\s*(?:hr|h|min)(?:\s*\d+\s*min)?$")
_DIST_TEXT_RE = re.compile(r"^[\d.,]+\s*(?:km|m|mi)$")
_STEP_RE = re.compile(r"^(?:Head|Turn|Continue|Take|Keep|Merge|Exit|Walk|Board|Get off|Ride|Destination|Slight|Sharp|Roundabout|At )")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(?:\s?[AP]M)?$")
_TRANSIT_RE = re.compile(r"^(?:Bus|Subway|Underground|Train|Tram|Light rail|DLR|Overground|Metro|Rail)$")


def build_directions_pb(origin: tuple[float, float], dest: tuple[float, float], mode: str) -> str:
    if mode not in MODE_FLAG:
        raise ValueError(f"unknown travel mode: {mode!r}")
    template = _TEMPLATE_PATH.read_text(encoding="utf-8").strip()
    return (
        template.replace("{OLAT}", str(origin[0]))
        .replace("{OLNG}", str(origin[1]))
        .replace("{DLAT}", str(dest[0]))
        .replace("{DLNG}", str(dest[1]))
        .replace("{MODE}", MODE_FLAG[mode])
    )


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
    duration_text = next((s for s in strings if _DUR_TEXT_RE.match(s)), None)
    distance_text = next((s for s in strings if _DIST_TEXT_RE.match(s)), None)
    steps: list[Step] = [Step(instruction=_clean(s)) for s in strings if _STEP_RE.match(s) and len(s) < 120]
    if mode == "transit":
        line = next((s for s in strings if _TRANSIT_RE.match(s)), None)
        times = [s for s in strings if _TIME_RE.match(s)]
        if line is not None or times:
            steps.insert(
                0,
                Step(
                    instruction="transit",
                    line=line,
                    departure=times[0] if times else None,
                    arrival=times[-1] if times else None,
                ),
            )
    return DirectionsLeg(mode=mode, duration_text=duration_text, distance_text=distance_text, steps=steps)
