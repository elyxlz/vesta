"""Place-detail RPC: build the replayable request and parse one place's detail.

The request rides a captured `pb` template (`place_pb.txt`) with a `{CID_HEX}` slot (the place's
cid in hex). Google does not validate the session token in that `pb`, so the template carries a
fixed placeholder. The response holds the place proto at element 6, read via `proto.py`; fields
it does not carry (full weekly hours, review text) stay null.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import proto
from .links import Stop, directions_url, place_url
from .models import Links, PlaceDetail
from .pb import json_strings, strip_envelope

_TEMPLATE_PATH = Path(__file__).with_name("place_pb.txt")
_REVERSE_TEMPLATE_PATH = Path(__file__).with_name("reverse_pb.txt")
# A reverse label is a street address ("Via Roma, 5, Rome, Italy") or a Plus Code
# ("WF3W+4HC Rome, ...") for open ground; both have a comma and letters.
_REVERSE_LABEL_RE = re.compile(r'"([^"\[\]{}:]{8,90})"')
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_PLACE_ID_RE = re.compile(r"^ChIJ[\w-]{10,}$")
_RANGE_RE = re.compile(r"^\d{1,2}\S*\s?(?:am|pm|AM|PM).+")
_PHOTO_RE = re.compile(r"^https://lh\d\.googleusercontent\.com/")


def build_place_pb(cid: int) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8").strip()
    return template.replace("{CID_HEX}", format(cid, "x"))


def build_reverse_pb(lat: float, lng: float) -> str:
    template = _REVERSE_TEMPLATE_PATH.read_text(encoding="utf-8").strip()
    return template.replace("{COORDS}", f"{lat},{lng}")


def parse_reverse(raw_body: str) -> str | None:
    """The reverse-geocoded label for a coordinate: the longest street-address or Plus-Code string."""
    clean = strip_envelope(raw_body)
    candidates = [
        s
        for s in _REVERSE_LABEL_RE.findall(clean)
        if s.count(", ") >= 1 and re.search(r"[A-Za-z]{4}", s) and not s.startswith(("0x", "http", "gcid", "/g/"))
    ]
    return max(candidates, key=len) if candidates else None


def _today_hours(strings: list[str]) -> str | None:
    for i, text in enumerate(strings):
        if text in _DAYS:
            span = strings[i : i + 6]
            return next((s for s in span if _RANGE_RE.match(s)), None)
    return None


def parse_place(raw_body: str, cid: int) -> PlaceDetail:
    data = json.loads(strip_envelope(raw_body))
    raw_proto = data[6] if isinstance(data, list) and len(data) > 6 else None
    place_proto = raw_proto if isinstance(raw_proto, list) else None
    strings = json_strings(data)
    name = proto.name(place_proto) or ""
    coord = proto.coords(place_proto)
    lat, lng = coord if coord is not None else (None, None)
    place_id = next((s for s in strings if _PLACE_ID_RE.match(s)), None)
    return PlaceDetail(
        name=name,
        cid=cid,
        place_id=place_id,
        ftid=proto.ftid(place_proto),
        address=proto.address(place_proto),
        lat=lat,
        lng=lng,
        rating=proto.rating(place_proto),
        category=proto.category(place_proto),
        phone=proto.phone(place_proto),
        website=proto.website(place_proto),
        hours_today=_today_hours(strings),
        open_intervals=proto.open_intervals(place_proto),
        photos=[s for s in strings if _PHOTO_RE.match(s)][:3],
        links=Links(
            place_url=place_url(cid),
            directions_url=(directions_url(Stop(name=name, lat=lat or 0.0, lng=lng or 0.0, place_id=place_id)) if name else place_url(cid)),
        ),
    )
