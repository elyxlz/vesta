"""Transparent identity cache: search and show populate it, directions reads it.

Holds only stable identity (name, coordinates, ftid, place_id) keyed by cid, so `directions
--to <cid>` resolves without a network call right after a search. The source of truth is Google;
this is a speed-up, safe to delete anytime, so a corrupt or missing file simply reads as empty.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import TypedDict, TypeGuard

from .links import Stop

_TTL_S = 7 * 24 * 3600  # identity is stable, so a generous window is safe
_MAX_ENTRIES = 500


class _Entry(TypedDict):
    name: str
    lat: float
    lng: float
    ftid: str | None
    place_id: str | None
    ts: float


def _is_entry(value: object) -> TypeGuard[_Entry]:
    if not isinstance(value, dict):
        return False
    for key, kind in (("name", str), ("lat", float), ("lng", float), ("ts", float)):
        if key not in value or not isinstance(value[key], kind):
            return False
    return all(key in value and (value[key] is None or isinstance(value[key], str)) for key in ("ftid", "place_id"))


def _cache_path() -> Path:
    base = os.environ["GMAPS_CACHE_DIR"] if "GMAPS_CACHE_DIR" in os.environ else str(Path.home() / ".gmaps")
    return Path(base) / "places.json"


def _load() -> dict[str, _Entry]:
    path = _cache_path()
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}  # a corrupt cache is rebuilt from the next search
    if not isinstance(loaded, dict):
        return {}
    return {cid: entry for cid, entry in loaded.items() if _is_entry(entry)}


def _save(data: dict[str, _Entry], now: float) -> None:
    fresh = {cid: entry for cid, entry in data.items() if now - entry["ts"] <= _TTL_S}
    if len(fresh) > _MAX_ENTRIES:
        newest = sorted(fresh.items(), key=lambda item: item[1]["ts"], reverse=True)[:_MAX_ENTRIES]
        fresh = dict(newest)
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fresh), encoding="utf-8")


def put(*, cid: int, name: str, lat: float, lng: float, ftid: str | None, place_id: str | None) -> None:
    now = time.time()
    data = _load()
    data[str(cid)] = _Entry(name=name, lat=lat, lng=lng, ftid=ftid, place_id=place_id, ts=now)
    _save(data, now)


def get(cid: int) -> Stop | None:
    data = _load()
    key = str(cid)
    if key not in data:
        return None
    entry = data[key]
    if time.time() - entry["ts"] > _TTL_S:
        return None
    return Stop(name=entry["name"], lat=entry["lat"], lng=entry["lng"], place_id=entry["place_id"], ftid=entry["ftid"])
