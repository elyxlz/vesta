"""Parser over Google's search response.

Google's arrays are positional and undocumented. Both response shapes, the list feed and the
single-entity answer a famous-landmark query gets, carry one place proto per result, so the walk
collects each proto subtree and reads the place from its pinned positions (`proto.py`).
"""

from __future__ import annotations

import re

from . import proto
from .links import Stop, cid_from_ftid, directions_url, place_url
from .models import Links, Place
from .pb import json_strings

_PLACE_ID_RE = re.compile(r"^ChIJ[\w-]{10,}$")


def _protos(feed: object) -> list[list[object]]:
    """Every place proto in the feed, in document order, without descending into one."""
    found: list[list[object]] = []

    def walk(node: object) -> None:
        if not isinstance(node, list):
            return
        if proto.is_proto(node):
            found.append(node)
            return
        for child in node:
            walk(child)

    walk(feed)
    return found


def parse_search(feed: object) -> list[Place]:
    places: list[Place] = []
    seen: set[str] = set()
    for place_proto in _protos(feed):
        ftid = proto.ftid(place_proto)
        name = proto.name(place_proto)
        coord = proto.coords(place_proto)
        if ftid is None or name is None or coord is None or ftid in seen:
            continue
        seen.add(ftid)
        cid = cid_from_ftid(ftid)
        lat, lng = coord
        place_id = next((s for s in json_strings(place_proto) if _PLACE_ID_RE.match(s)), None)
        places.append(
            Place(
                name=name,
                lat=lat,
                lng=lng,
                ftid=ftid,
                cid=cid,
                place_id=place_id,
                address=proto.address(place_proto),
                rating=proto.rating(place_proto),
                review_count=proto.review_count(place_proto),
                category=proto.category(place_proto),
                phone=proto.phone(place_proto),
                website=proto.website(place_proto),
                open_now=proto.open_now(place_proto),
                links=Links(
                    place_url=place_url(cid),
                    directions_url=directions_url(Stop(name=name, lat=lat, lng=lng, place_id=place_id, ftid=ftid)),
                ),
            )
        )
    return places
