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

from .links import Stop

_TTL_S = 7 * 24 * 3600  # identity is stable, so a generous window is safe
_MAX_ENTRIES = 500


def _cache_path() -> Path:
    base = os.environ["GMAPS_CACHE_DIR"] if "GMAPS_CACHE_DIR" in os.environ else str(Path.home() / ".gmaps")
    return Path(base) / "places.json"


def _load() -> dict[str, dict[str, object]]:
    path = _cache_path()
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}  # a corrupt cache is rebuilt from the next search
    return loaded if isinstance(loaded, dict) else {}


def _save(data: dict[str, dict[str, object]], now: float) -> None:
    fresh = {cid: entry for cid, entry in data.items() if now - float(entry["ts"]) <= _TTL_S}
    if len(fresh) > _MAX_ENTRIES:
        newest = sorted(fresh.items(), key=lambda item: float(item[1]["ts"]), reverse=True)[:_MAX_ENTRIES]
        fresh = dict(newest)
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fresh), encoding="utf-8")


def put(*, cid: int, name: str, lat: float, lng: float, ftid: str | None, place_id: str | None) -> None:
    now = time.time()
    data = _load()
    data[str(cid)] = {"name": name, "lat": lat, "lng": lng, "ftid": ftid, "place_id": place_id, "ts": now}
    _save(data, now)


def get(cid: int) -> Stop | None:
    data = _load()
    key = str(cid)
    if key not in data:
        return None
    entry = data[key]
    if time.time() - float(entry["ts"]) > _TTL_S:
        return None
    return Stop(
        name=str(entry["name"]),
        lat=float(entry["lat"]),
        lng=float(entry["lng"]),
        place_id=str(entry["place_id"]) if entry["place_id"] is not None else None,
        ftid=str(entry["ftid"]) if entry["ftid"] is not None else None,
    )
