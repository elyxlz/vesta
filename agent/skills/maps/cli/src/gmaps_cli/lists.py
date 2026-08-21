"""Read and manage the user's Google Maps saved lists over the signed-in browser.

Composes the browser transport (`browser_bridge`) with the `entitylist` pb builders and turns the
positional response arrays into typed models. The unauthenticated maps commands never reach here.
"""

from __future__ import annotations

from . import browser_bridge, list_pb
from .models import MapList


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
