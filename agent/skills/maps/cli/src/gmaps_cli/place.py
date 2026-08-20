"""Place-detail RPC: build the replayable request and parse one place's detail.

The request rides a captured `pb` template (`place_pb.txt`) with a `{CID_HEX}` slot (the place's
cid in hex). Google does not validate the session token in that `pb`, so the template carries a
fixed placeholder. The response carries the fields mapped below; those it does not carry (full
weekly hours, review text) stay null.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .links import Stop, directions_url, place_url
from .models import Links, PlaceDetail
from .pb import strip_envelope

_TEMPLATE_PATH = Path(__file__).with_name("place_pb.txt")
_REVERSE_TEMPLATE_PATH = Path(__file__).with_name("reverse_pb.txt")
# A reverse label is a street address ("Via Roma, 5, Rome, Italy") or a Plus Code
# ("WF3W+4HC Rome, ...") for open ground; both have a comma and letters.
_REVERSE_LABEL_RE = re.compile(r'"([^"\[\]{}:]{8,90})"')
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_PLACE_ID_RE = re.compile(r"^ChIJ[\w-]{10,}$")
_PHONE_RE = re.compile(r"^\+[\d][\d ]{6,}$")
_RANGE_RE = re.compile(r"^\d{1,2}\S*\s?(?:am|pm|AM|PM).+")
_FTID_RE = re.compile(r"0x[0-9a-f]{6,}:0x[0-9a-f]{6,}")
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


def _floats(node: object) -> list[float]:
    out: list[float] = []

    def walk(value: object) -> None:
        if isinstance(value, float):
            out.append(value)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(node)
    return out


_E7 = 10_000_000


def _first_coord_e7(node: object) -> tuple[float, float] | None:
    """Coordinates are stored as a [lat_e7, lng_e7] integer pair (degrees * 1e7)."""
    if isinstance(node, list):
        if (
            len(node) == 2
            and isinstance(node[0], int)
            and isinstance(node[1], int)
            and not isinstance(node[0], bool)
            and abs(node[0]) <= 90 * _E7
            and abs(node[1]) <= 180 * _E7
            and abs(node[0]) >= _E7
        ):
            return (node[0] / _E7, node[1] / _E7)
        for child in node:
            found = _first_coord_e7(child)
            if found is not None:
                return found
    return None


def _str_at(node: object, *path: int) -> str | None:
    """Follow a fixed index path; return the string there, or None if absent/not a string."""
    current: object = node
    for index in path:
        if not isinstance(current, list) or not -len(current) <= index < len(current):
            return None
        current = current[index]
    return current if isinstance(current, str) else None


def _is_web(url: str) -> bool:
    return url.startswith(("http://", "https://")) and not any(
        host in url for host in ("google", "gstatic", "ggpht", "schema.org", "lh3", "lh4", "lh5")
    )


def _today_hours(strings: list[str]) -> str | None:
    for i, text in enumerate(strings):
        if text in _DAYS:
            span = strings[i : i + 6]
            return next((s for s in span if _RANGE_RE.match(s)), None)
    return None


def parse_place(raw_body: str, cid: int) -> PlaceDetail:
    clean = strip_envelope(raw_body)
    data = json.loads(clean)
    strings = _strings(data)
    # Name and address sit at pinned positions in the place-data section (data[6]).
    name = _str_at(data, 6, 11) or ""
    address = _str_at(data, 6, 39)
    place_id = next((s for s in strings if _PLACE_ID_RE.match(s)), None)
    ftid_match = _FTID_RE.search(clean)
    ftid = ftid_match.group(0) if ftid_match is not None else None
    phone = next((s for s in strings if _PHONE_RE.match(s)), None)
    website = next((s for s in strings if _is_web(s)), None)
    photos = [s for s in strings if _PHOTO_RE.match(s)][:3]
    category = next((m.group(1).replace("_", " ") for m in (re.match(r"gcid:(\w+)", s) for s in strings) if m), None)
    rating = next((f for f in _floats(data) if 1.0 <= f <= 5.0), None)
    coord = _first_coord_e7(data)
    lat, lng = coord if coord is not None else (None, None)
    return PlaceDetail(
        name=name,
        cid=cid,
        place_id=place_id,
        ftid=ftid,
        address=address,
        lat=lat,
        lng=lng,
        rating=rating,
        category=category,
        phone=phone,
        website=website,
        hours_today=_today_hours(strings),
        photos=photos,
        links=Links(
            place_url=place_url(cid),
            directions_url=(directions_url(Stop(name=name, lat=lat or 0.0, lng=lng or 0.0, place_id=place_id)) if name else place_url(cid)),
        ),
    )
