"""Network client: replays the search and directions RPCs and applies client-side filters.

Stateless and paced. Search is two GETs (page for a session token, then the RPC); directions is
one GET per mode. Parsing lives in `parse.py`; this module is the IO edge.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from dataclasses import dataclass

import httpx

from .directions import build_directions_pb, parse_directions
from .itinerary import haversine_km, lay_out, nearest_neighbour, parse_duration_min
from .links import Stop, route_url
from .models import DirectionsLeg, ItineraryStop, Place, PlaceDetail
from .parse import parse_search
from .pb import build_search_pb, extract_session_token, strip_envelope
from .place import build_place_pb, build_reverse_pb, parse_place, parse_reverse

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
CONSENT_COOKIE = "CONSENT=YES+cb.20210328-17-p0.en+FX+678; SOCS=CAI"
REQUEST_DELAY_S = 0.8
REQUEST_TIMEOUT_S = 30.0
CANARY_QUERY = "coffee"


class BlockedError(RuntimeError):
    """Google returned a consent wall or challenge rather than data."""


class DriftError(RuntimeError):
    """A known-good canary query also returned nothing: the pb schema likely drifted."""


@dataclass
class SearchFilters:
    min_rating: float | None = None
    category: str | None = None
    radius_km: float | None = None
    sort: str | None = None  # "distance" | "rating"
    limit: int = 20


def _client(locale: str) -> httpx.Client:
    return httpx.Client(
        headers={
            "User-Agent": USER_AGENT,
            "Cookie": CONSENT_COOKIE,
            "Accept-Language": f"{locale},{locale.split('-', maxsplit=1)[0]};q=0.9",
        },
        timeout=REQUEST_TIMEOUT_S,
        follow_redirects=True,
    )


def _get(client: httpx.Client, url: str) -> str:
    time.sleep(REQUEST_DELAY_S)
    resp = client.get(url)
    if "consent.google.com" in str(resp.url) or resp.status_code == 429:
        raise BlockedError(f"blocked ({resp.status_code}) at {resp.url}")
    return resp.text


def _search_feed(client: httpx.Client, query: str, *, lang: str, country: str) -> object:
    quoted = urllib.parse.quote(query)
    page = _get(client, f"https://www.google.com/maps/search/{quoted}?hl={lang}&gl={country}")
    token = extract_session_token(page)
    pb = build_search_pb(query, token)
    # The `q` param is load-bearing: without it Google serves the HTML page, not the map RPC.
    raw = _get(client, f"https://www.google.com/search?tbm=map&authuser=0&hl={lang}&gl={country}&q={quoted}&pb={pb}")
    return json.loads(strip_envelope(raw))


def search(query: str, *, near: str | None, filters: SearchFilters, locale: str, country: str) -> list[Place]:
    near_latlng = _near_latlng(near)
    if (filters.radius_km is not None or filters.sort == "distance") and near_latlng is None:
        raise ValueError("--radius-km and --sort distance need --near as lat,lng")
    lang = locale.split("-", maxsplit=1)[0]
    with _client(locale) as client:
        full_query = f"{query} {near}" if near else query
        feed = _search_feed(client, full_query, lang=lang, country=country)
        places = parse_search(feed)
        if not places:
            # Drift canary: a known-good query that comes back empty means the schema moved.
            canary = parse_search(_search_feed(client, CANARY_QUERY, lang=lang, country=country))
            if not canary:
                raise DriftError("search returned nothing and the canary is empty; recapture the pb template")
        return _apply_filters(places, filters, near_latlng=near_latlng)


def show(cid: int, *, locale: str, country: str) -> PlaceDetail:
    lang = locale.split("-", maxsplit=1)[0]
    pb = build_place_pb(cid)
    with _client(locale) as client:
        raw = _get(client, f"https://www.google.com/maps/preview/place?authuser=0&hl={lang}&gl={country}&pb={pb}")
    return parse_place(raw, cid)


def reverse(lat: float, lng: float, *, locale: str, country: str) -> str | None:
    lang = locale.split("-", maxsplit=1)[0]
    pb = build_reverse_pb(lat, lng)
    quoted = urllib.parse.quote(f"{lat},{lng}")
    with _client(locale) as client:
        raw = _get(client, f"https://www.google.com/maps/preview/place?authuser=0&hl={lang}&gl={country}&q={quoted}&pb={pb}")
    return parse_reverse(raw)


def directions(
    origin: tuple[float, float],
    dest: tuple[float, float],
    *,
    mode: str,
    locale: str,
    country: str,
) -> DirectionsLeg:
    lang = locale.split("-", maxsplit=1)[0]
    pb = build_directions_pb(origin, dest, mode)
    with _client(locale) as client:
        raw = _get(client, f"https://www.google.com/maps/preview/directions?authuser=0&hl={lang}&gl={country}&pb={pb}")
    return parse_directions(raw, mode)


def itinerary(
    cids: list[int],
    *,
    mode: str,
    start: str,
    dwell_min: int,
    optimize: bool,
    locale: str,
    country: str,
) -> dict[str, object]:
    stops = [show(cid, locale=locale, country=country) for cid in cids]
    if any(s.lat is None or s.lng is None for s in stops):
        raise ValueError("every stop needs coordinates; one place returned none")
    coords = [(s.lat, s.lng) for s in stops if s.lat is not None and s.lng is not None]
    if optimize:
        order = nearest_neighbour(coords)
        stops = [stops[i] for i in order]
        coords = [coords[i] for i in order]
    legs = [directions(coords[i], coords[i + 1], mode=mode, locale=locale, country=country) for i in range(len(stops) - 1)]
    leg_minutes = [parse_duration_min(leg.duration_text) for leg in legs]
    slots = lay_out(leg_minutes, start=start, dwell_min=dwell_min, count=len(stops))
    itinerary_stops = [
        ItineraryStop(place=stop, arrive=arrive, leave=leave, open_at_slot=None) for stop, (arrive, leave) in zip(stops, slots, strict=True)
    ]
    route_stops = [Stop(name=s.name, lat=lat, lng=lng, place_id=s.place_id) for s, (lat, lng) in zip(stops, coords, strict=True)]
    return {
        "stops": [s.to_json() for s in itinerary_stops],
        "legs": [{"from": stops[i].name, "to": stops[i + 1].name, "mode": mode, "duration": legs[i].duration_text} for i in range(len(legs))],
        "route_url": route_url(route_stops, mode=mode) if len(route_stops) >= 2 else None,
        "total_minutes": sum(leg_minutes) + dwell_min * len(stops),
    }


def _near_latlng(near: str | None) -> tuple[float, float] | None:
    if near is None:
        return None
    parts = near.split(",")
    if len(parts) == 2:
        try:
            return (float(parts[0]), float(parts[1]))
        except ValueError:
            return None
    return None


def _apply_filters(places: list[Place], filters: SearchFilters, *, near_latlng: tuple[float, float] | None) -> list[Place]:
    out = places
    if filters.min_rating is not None:
        out = [p for p in out if p.rating is not None and p.rating >= filters.min_rating]
    if filters.category is not None:
        needle = filters.category.lower()
        out = [p for p in out if p.category is not None and needle in p.category.lower()]
    if filters.radius_km is not None and near_latlng is not None:
        out = [p for p in out if haversine_km(near_latlng, (p.lat, p.lng)) <= filters.radius_km]
    if filters.sort == "rating":
        out = sorted(out, key=lambda p: p.rating or 0.0, reverse=True)
    elif filters.sort == "distance" and near_latlng is not None:
        out = sorted(out, key=lambda p: haversine_km(near_latlng, (p.lat, p.lng)))
    return out[: filters.limit]
