"""Read and manage the user's Google Maps saved lists over the signed-in browser.

Composes the browser transport (`browser_bridge`) with the `entitylist` pb builders and turns the
positional response arrays into typed models. The unauthenticated maps commands never reach here.
"""

from __future__ import annotations

from . import browser_bridge, cache, client, list_pb
from .models import MapList, MapListItem


def _share_url(entry: list[object]) -> str | None:
    for field in entry:
        if isinstance(field, list):
            for value in field:
                if isinstance(value, str) and "placelists/list/" in value:
                    return value
    return None


def list_all() -> list[MapList]:
    raw = browser_bridge.entitylist_get("list", list_pb.list_index_pb())
    top = raw[0] if isinstance(raw, list) and raw and isinstance(raw[0], list) else []
    out: list[MapList] = []
    for entry in top:
        if not isinstance(entry, list) or not entry:
            continue
        header = entry[0]
        list_id = header[0] if isinstance(header, list) and header else None
        if not isinstance(list_id, str):
            continue  # system collection, not a user list
        kind = header[1] if len(header) > 1 and isinstance(header[1], int) else 0
        name = entry[4] if len(entry) > 4 and isinstance(entry[4], str) else ""
        out.append(MapList(id=list_id, name=name, kind=kind, item_count=None, share_url=_share_url(entry)))
    return out


def _parse_item(raw_item: list[object]) -> MapListItem | None:
    """One item entry: name at [2], place core at [1] with ftid pair at [1][6] (decimal strings)."""
    if not isinstance(raw_item, list) or len(raw_item) < 3:
        return None
    name = raw_item[2] if isinstance(raw_item[2], str) else ""
    place = raw_item[1]
    if not isinstance(place, list) or len(place) < 7:
        return None
    ftid_pair = place[6]
    if not isinstance(ftid_pair, list) or len(ftid_pair) < 2 or not isinstance(ftid_pair[1], str):
        return None
    note = raw_item[3] if len(raw_item) > 3 and isinstance(raw_item[3], str) and raw_item[3] else None
    # getlist gives the ftid halves as signed 64-bit decimals; the rest of the skill keys on the
    # unsigned cid (int of the hex half), so normalise here or a shown cid never matches a search one.
    cid = int(ftid_pair[1]) % (2**64)
    return MapListItem(name=name, cid=cid, note=note)


def get_list(list_id: str) -> list[MapListItem]:
    raw = browser_bridge.entitylist_get("getlist", list_pb.getlist_pb(list_id))
    entry = raw[0] if isinstance(raw, list) and raw and isinstance(raw[0], list) else []
    items_raw = entry[8] if len(entry) > 8 and isinstance(entry[8], list) else []
    items = [_parse_item(it) for it in items_raw]
    return [item for item in items if item is not None]


def create(name: str) -> str:
    raw = browser_bridge.entitylist_write("create", lambda token, consistency: list_pb.create_pb(name, token, consistency))
    header = raw[0][0] if isinstance(raw, list) and raw and isinstance(raw[0], list) and raw[0] and isinstance(raw[0][0], list) else None
    if header is None or not header or not isinstance(header[0], str):
        raise ValueError("create returned no list id")
    return header[0]


def rename(list_id: str, name: str) -> None:
    browser_bridge.entitylist_write("update", lambda token, consistency: list_pb.rename_pb(list_id, name, token, consistency))


def delete(list_id: str) -> None:
    browser_bridge.entitylist_write("delete", lambda token, consistency: list_pb.delete_pb(list_id, token, consistency))


def _place_identity(cid: int, *, locale: str, country: str) -> tuple[str, float, float, str]:
    """A place's name, coordinates, and ftid from the cache, else a `show` fetch (then cached)."""
    cached = cache.get(cid)
    if cached is not None and cached.ftid is not None:
        return cached.name, cached.lat, cached.lng, cached.ftid
    detail = client.show(cid, locale=locale, country=country)
    if detail.ftid is None or detail.lat is None or detail.lng is None:
        raise ValueError(f"place {cid} has no ftid or coordinates, so it cannot go in a list")
    cache.put(cid=detail.cid, name=detail.name, lat=detail.lat, lng=detail.lng, ftid=detail.ftid, place_id=detail.place_id)
    return detail.name, detail.lat, detail.lng, detail.ftid


def add_item(list_id: str, cid: int, *, locale: str, country: str) -> None:
    name, lat, lng, ftid = _place_identity(cid, locale=locale, country=country)
    browser_bridge.entitylist_write("createitem", lambda token, consistency: list_pb.item_pb(list_id, name, lat, lng, ftid, token, consistency))


def remove_item(list_id: str, cid: int, *, locale: str, country: str) -> None:
    name, lat, lng, ftid = _place_identity(cid, locale=locale, country=country)
    browser_bridge.entitylist_write("deleteitem", lambda token, consistency: list_pb.item_pb(list_id, name, lat, lng, ftid, token, consistency))
