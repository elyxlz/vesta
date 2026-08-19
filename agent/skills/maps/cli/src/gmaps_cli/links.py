"""Pure Google Maps link builders and the SAPISIDHASH signer. No network.

Links are the durable, shareable output. The `cid` (Google's numeric place id) opens the exact
place; a `place_id` (ChIJ...) passed alongside a name renders a named stop rather than a dropped
pin. Coordinates alone drop a pin, so a route uses place_ids when it has them.
"""

from __future__ import annotations

import hashlib
import urllib.parse
from dataclasses import dataclass

MAPS_ORIGIN = "https://www.google.com"
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


def _latlng(lat: float, lng: float) -> str:
    return f"{lat},{lng}"


def directions_url(
    dest: tuple[float, float],
    *,
    origin: tuple[float, float] | None = None,
    mode: str = "driving",
) -> str:
    if mode not in TRAVEL_MODES:
        raise ValueError(f"unknown travel mode: {mode!r}")
    params: dict[str, str] = {"api": "1", "destination": _latlng(*dest), "travelmode": mode}
    if origin is not None:
        params["origin"] = _latlng(*origin)
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


def sapisidhash(sapisid: str, ts: int, origin: str = MAPS_ORIGIN) -> str:
    """Google's cookie-auth signature: `<ts>_<sha1("<ts> <SAPISID> <origin>")>`.

    Used only by the authenticated saved-lists path; the shipped anonymous scope never calls it.
    """
    payload = f"{ts} {sapisid} {origin}"
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"{ts}_{digest}"
