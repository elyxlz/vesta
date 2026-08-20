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
    ftid: str | None = None


def cid_from_ftid(ftid: str) -> int:
    """The decimal cid is the second hex half of the ftid (`0x<a>:0x<b>` -> int(b, 16))."""
    parts = ftid.split(":")
    if len(parts) != 2:
        raise ValueError(f"malformed ftid: {ftid!r}")
    return int(parts[1], 16)


def place_url(cid: int) -> str:
    return f"https://maps.google.com/?cid={cid}"


def directions_url(dest: Stop, *, origin: Stop | None = None, mode: str = "driving") -> str:
    """A directions link addressed by place_id where available (exact), name otherwise.

    The name is the display fallback; the place_id pins the exact place, so a shared name never
    resolves to the wrong branch.
    """
    if mode not in TRAVEL_MODES:
        raise ValueError(f"unknown travel mode: {mode!r}")
    params: dict[str, str] = {"api": "1", "destination": dest.name, "travelmode": mode}
    if dest.place_id is not None:
        params["destination_place_id"] = dest.place_id
    if origin is not None:
        params["origin"] = origin.name
        if origin.place_id is not None:
            params["origin_place_id"] = origin.place_id
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


def _exact_endpoint(stop: Stop) -> str:
    """The data= block pinning one endpoint by ftid + coordinates."""
    return f"!1m5!1m1!1s{stop.ftid}!2m2!1d{stop.lng}!2d{stop.lat}"


def transit_time_url(dest: Stop, origin: Stop, *, kind: str, epoch: int) -> str:
    """A /maps/dir/ link opening transit directions with a depart-at or arrive-by time set.

    Pins each endpoint by ftid + coordinates when known (exact), else by name in the path (Maps
    geocodes it). The time rides the `data=` param as `!8j<epoch>`; `6e0` = depart, `6e1` = arrive.
    """
    if kind not in ("depart", "arrive"):
        raise ValueError(f"kind must be 'depart' or 'arrive', got {kind!r}")
    when = "6e0" if kind == "depart" else "6e1"
    origin_q, dest_q = urllib.parse.quote(origin.name), urllib.parse.quote(dest.name)
    time_block = f"!2m3!{when}!7e2!8j{epoch}!3e3"
    if origin.ftid is not None and dest.ftid is not None:
        data = f"!4m18!4m17{_exact_endpoint(origin)}{_exact_endpoint(dest)}{time_block}"
    else:
        data = f"!4m6!4m5{time_block}"
    return f"https://www.google.com/maps/dir/{origin_q}/{dest_q}/data={data}"
