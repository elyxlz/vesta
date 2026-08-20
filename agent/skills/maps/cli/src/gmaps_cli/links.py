"""Pure Google Maps link builders. No network.

Links are the durable, shareable output. The `cid` (Google's numeric place id) opens the exact
place; a `place_id` (ChIJ...) passed alongside a name renders a named stop rather than a dropped
pin. Coordinates alone drop a pin, so a route uses place_ids when it has them.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

TRAVEL_MODES = ("driving", "transit", "walking", "bicycling")


@dataclass
class Stop:
    name: str
    lat: float
    lng: float
    place_id: str | None = None


def cid_from_ftid(ftid: str) -> int:
    """The decimal cid is the second hex half of the ftid (`0x<a>:0x<b>` -> int(b, 16))."""
    parts = ftid.split(":")
    if len(parts) != 2:
        raise ValueError(f"malformed ftid: {ftid!r}")
    return int(parts[1], 16)


def place_url(cid: int) -> str:
    return f"https://maps.google.com/?cid={cid}"


def directions_url(dest_name: str, *, origin_name: str | None = None, mode: str = "driving") -> str:
    """A directions link addressed by place name, so Maps shows named places, not dropped pins."""
    if mode not in TRAVEL_MODES:
        raise ValueError(f"unknown travel mode: {mode!r}")
    params: dict[str, str] = {"api": "1", "destination": dest_name, "travelmode": mode}
    if origin_name is not None:
        params["origin"] = origin_name
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(params)


def route_url(stops: list[Stop], *, mode: str = "driving") -> str:
    """A single multi-stop directions link. Uses place_ids so stops render named, not as pins."""
    if mode not in TRAVEL_MODES:
        raise ValueError(f"unknown travel mode: {mode!r}")
    if len(stops) < 2:
        raise ValueError("a route needs at least two stops")
    origin, dest = stops[0], stops[-1]
    mids = stops[1:-1]
    params: dict[str, str] = {
        "api": "1",
        "origin": origin.name,
        "destination": dest.name,
        "travelmode": mode,
    }
    if origin.place_id is not None:
        params["origin_place_id"] = origin.place_id
    if dest.place_id is not None:
        params["destination_place_id"] = dest.place_id
    if mids:
        params["waypoints"] = "|".join(s.name for s in mids)
        if all(s.place_id is not None for s in mids):
            params["waypoint_place_ids"] = "|".join(s.place_id for s in mids if s.place_id)
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(params, safe="|")


def transit_time_url(dest_name: str, origin_name: str, *, kind: str, epoch: int) -> str:
    """A /maps/dir/ link opening transit directions with a depart-at or arrive-by time set.

    Addressed by place name (so no dropped pins). The time rides the `data=` param as
    `!8j<epoch>`; `6e0` = depart at, `6e1` = arrive by.
    """
    if kind not in ("depart", "arrive"):
        raise ValueError(f"kind must be 'depart' or 'arrive', got {kind!r}")
    when = "6e0" if kind == "depart" else "6e1"
    origin_q, dest_q = urllib.parse.quote(origin_name), urllib.parse.quote(dest_name)
    return f"https://www.google.com/maps/dir/{origin_q}/{dest_q}/data=!4m6!4m5!2m3!{when}!7e2!8j{epoch}!3e3"
