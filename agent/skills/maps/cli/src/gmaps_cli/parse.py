"""Parser over Google's positional search array.

Google's arrays are positional and undocumented, so this extracts the fields whose positions are
pinned by the dev captures and leaves the rest null. The walk anchors each place on its ftid (one
per place) and reads the name, address, coordinates, and rating that sit beside it.
"""

from __future__ import annotations

import re

from .links import Stop, cid_from_ftid, directions_url, place_url
from .models import Links, Place
from .pb import is_web_url, json_strings

_FTID_RE = re.compile(r"^0x[0-9a-f]+:0x[0-9a-f]+$")
_FTID_RE_ANY = re.compile(r"0x[0-9a-f]+:0x[0-9a-f]+")
_ADDR_RE = re.compile(r".+,.+\d.+")  # a street-ish string: has commas and a digit
_PLACE_ID_RE = re.compile(r"^ChIJ[\w-]{10,}$")
_LAT_MAX, _LNG_MAX = 90.0, 180.0


def _is_coord_triple(node: list[object]) -> bool:
    """A [_, lng, lat] point: element 1 and 2 are floats in valid geographic range."""
    return (
        len(node) >= 3
        and isinstance(node[1], float)
        and isinstance(node[2], float)
        and -_LNG_MAX <= node[1] <= _LNG_MAX
        and -_LAT_MAX <= node[2] <= _LAT_MAX
    )


def _first_coord(node: object) -> tuple[float, float] | None:
    if isinstance(node, list):
        lng, lat = node[1] if len(node) >= 3 else None, node[2] if len(node) >= 3 else None
        if isinstance(lng, float) and isinstance(lat, float) and -_LNG_MAX <= lng <= _LNG_MAX and -_LAT_MAX <= lat <= _LAT_MAX:
            return (lat, lng)
        for child in node:
            found = _first_coord(child)
            if found is not None:
                return found
    return None


def _first_rating(node: object) -> float | None:
    """The star rating is a bare float in [1.0, 5.0]. Coordinate triples are skipped, since a real
    longitude or latitude can also fall in that band and must never be read as a rating.
    """
    if isinstance(node, list):
        if _is_coord_triple(node):
            return None
        for child in node:
            found = _first_rating(child)
            if found is not None:
                return found
    elif isinstance(node, float) and 1.0 <= node <= 5.0:
        return node
    return None


def _place_records(feed: object) -> list[list[object]]:
    """The tightest subtrees holding exactly one ftid and an address string: one per place.

    Annotate every list node once (ftid count + whether it holds an address), then descend only
    until a node isolates a single place, so the search feed is walked in linear time.
    """
    ftids: dict[int, frozenset[str]] = {}
    has_address: dict[int, bool] = {}

    def annotate(node: object) -> tuple[frozenset[str], bool]:
        if isinstance(node, str):
            return (frozenset(_FTID_RE_ANY.findall(node)), bool(_ADDR_RE.match(node)))
        if isinstance(node, list):
            found: set[str] = set()
            address = False
            for child in node:
                child_ftids, child_address = annotate(child)
                found |= child_ftids
                address = address or child_address
            ftids[id(node)] = frozenset(found)
            has_address[id(node)] = address
            return (frozenset(found), address)
        return (frozenset(), False)

    annotate(feed)

    records: list[list[object]] = []

    def select(node: object) -> None:
        if not isinstance(node, list):
            return
        if len(ftids[id(node)]) == 1 and has_address[id(node)]:
            records.append(node)
            return
        for child in node:
            select(child)

    select(feed)
    return records


def parse_search(feed: object) -> list[Place]:
    """Each place record is anchored on its ftid: name is the next string, categories follow."""
    places: list[Place] = []
    seen: set[str] = set()
    for record in _place_records(feed):
        strings = json_strings(record)
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
        website = next((s for s in strings if is_web_url(s)), None)
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
                links=Links(
                    place_url=place_url(cid),
                    directions_url=directions_url(Stop(name=name, lat=lat, lng=lng, place_id=place_id, ftid=ftid)),
                ),
            )
        )
    return places
