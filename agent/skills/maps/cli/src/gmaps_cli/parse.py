"""Parsers over Google's positional response arrays.

Google's arrays are positional and undocumented, so these extract the fields whose positions are
pinned by the dev captures and leave the rest null. The place-record walk anchors on the ftid
(one per place) and reads the name, address, and coordinates that sit beside it.
"""

from __future__ import annotations

import json
import re

from .links import cid_from_ftid, directions_url, place_url
from .models import DirectionsLeg, Links, Place, Step
from .pb import strip_envelope

_FTID_RE = re.compile(r"^0x[0-9a-f]+:0x[0-9a-f]+$")
_FTID_RE_ANY = re.compile(r"0x[0-9a-f]+:0x[0-9a-f]+")
_ADDR_RE = re.compile(r".+,.+\d.+")  # a street-ish string: has commas and a digit
_PLACE_ID_RE = re.compile(r"^ChIJ[\w-]{10,}$")
_DUR_TEXT_RE = re.compile(r"^\d+\s*(?:hr|h|min)(?:\s*\d+\s*min)?$")
_DIST_TEXT_RE = re.compile(r"^[\d.,]+\s*(?:km|m|mi)$")
_STEP_RE = re.compile(r"^(?:Head|Turn|Continue|Take|Keep|Merge|Exit|Walk|Board|Get off|Ride|Destination|Slight|Sharp|Roundabout|At )")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(?:\s?[AP]M)?$")
_TRANSIT_RE = re.compile(r"^(?:Bus|Subway|Underground|Train|Tram|Light rail|DLR|Overground|Metro|Rail)$")


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


def _first_coord(node: object) -> tuple[float, float] | None:
    """Find a [_, lng, lat] float triple (Google's order) anywhere in the subtree."""
    if isinstance(node, list):
        if (
            len(node) >= 3
            and isinstance(node[1], float)
            and isinstance(node[2], float)
            and -180.0 <= node[1] <= 180.0
            and -90.0 <= node[2] <= 90.0
        ):
            return (node[2], node[1])
        for child in node:
            found = _first_coord(child)
            if found is not None:
                return found
    return None


def _place_records(feed: object) -> list[list[object]]:
    """Smallest list subtrees that hold exactly one ftid and an address string: one per place."""
    records: list[list[object]] = []

    def walk(node: object) -> None:
        if not isinstance(node, list):
            return
        blob = json.dumps(node, ensure_ascii=False)
        ftids = _FTID_RE_ANY.findall(blob)
        if len(set(ftids)) == 1 and any(_ADDR_RE.match(s) for s in _strings(node)):
            records.append(node)
            return  # do not descend: this is the tightest record
        for child in node:
            walk(child)

    walk(feed)
    return records


def _first_rating(node: object) -> float | None:
    """The star rating is the one float in [1.0, 5.0] in a record (coordinates fall outside it)."""
    if isinstance(node, float):
        return node if 1.0 <= node <= 5.0 else None
    if isinstance(node, list):
        for child in node:
            found = _first_rating(child)
            if found is not None:
                return found
    return None


def _is_web(url: str) -> bool:
    return url.startswith(("http://", "https://")) and not any(
        host in url for host in ("google", "gstatic", "ggpht", "schema.org", "lh3", "lh4", "lh5")
    )


def parse_search(feed: object) -> list[Place]:
    """Each place record is anchored on its ftid: name is the next string, categories follow."""
    places: list[Place] = []
    seen: set[str] = set()
    for record in _place_records(feed):
        strings = _strings(record)
        ftid_index = next((i for i, s in enumerate(strings) if _FTID_RE.match(s)), None)
        if ftid_index is None or ftid_index + 1 >= len(strings):
            continue
        ftid = strings[ftid_index]
        if ftid in seen:
            continue
        coord = _first_coord(record)
        if coord is None:
            continue
        seen.add(ftid)
        name = strings[ftid_index + 1]
        combined = next((s for s in strings if s.startswith(f"{name}, ")), None)
        address = combined[len(name) + 2 :] if combined is not None else None
        category = strings[ftid_index + 2] if ftid_index + 2 < len(strings) else None
        if category is not None and (category == name or _ADDR_RE.match(category)):
            category = None
        website = next((s for s in strings if _is_web(s)), None)
        place_id = next((s for s in strings if _PLACE_ID_RE.match(s)), None)
        cid = cid_from_ftid(ftid)
        lat, lng = coord
        places.append(
            Place(
                name=name,
                lat=lat,
                lng=lng,
                ftid=ftid,
                cid=cid,
                place_id=place_id,
                address=address,
                rating=_first_rating(record),
                category=category,
                website=website,
                links=Links(place_url=place_url(cid), directions_url=directions_url((lat, lng))),
            )
        )
    return places


def _clean_step(text: str) -> str:
    return re.sub(r"</?b>", "", text).strip()


def parse_directions(raw_body: str, mode: str) -> DirectionsLeg:
    clean = strip_envelope(raw_body)
    data = json.loads(clean)
    strings = _strings(data)
    dur_text = next((s for s in strings if _DUR_TEXT_RE.match(s)), None)
    dist_text = next((s for s in strings if _DIST_TEXT_RE.match(s)), None)
    steps: list[Step] = [Step(instruction=_clean_step(text)) for text in strings if _STEP_RE.match(text) and len(text) < 120]
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
    return DirectionsLeg(
        mode=mode,
        duration_s=None,
        distance_m=None,
        duration_text=dur_text,
        distance_text=dist_text,
        steps=steps,
    )
