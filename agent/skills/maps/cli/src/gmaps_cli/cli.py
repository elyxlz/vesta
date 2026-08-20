"""`maps` command dispatch. Tables or JSON on stdout; errors as {"error": ...} on stderr, non-zero exit.

Stateless: every command takes durable Google ids or coordinates and stores nothing. The agent
keeps its own working set (trip files); see SKILL.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from . import cache
from .client import DOCTOR_ANCHOR_NAME, BlockedError, DriftError, SearchFilters, directions, doctor, itinerary, reverse, search, show
from .format import format_itinerary, format_place_detail, format_search_table
from .links import Stop, directions_url, route_url, transit_time_url


def _emit(payload: dict[str, object]) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def _fail(message: str) -> int:
    json.dump({"error": message}, sys.stderr, ensure_ascii=False)
    sys.stderr.write("\n")
    return 1


def _note(message: str) -> None:
    print(message, file=sys.stderr)


def _add_json_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true", help="compact JSON instead of a table")
    group.add_argument("--json-pretty", action="store_true", dest="json_pretty", help="indented JSON instead of a table")


def _emit_json(payload: object, args: argparse.Namespace) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.json_pretty else None))


def _coord(text: str) -> tuple[float, float]:
    lat, lng = text.split(",")
    return (float(lat), float(lng))


def _next_epoch(hhmm: str, tz_name: str) -> int:
    """Unix epoch for the next occurrence of HH:MM in the given IANA timezone."""
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone: {tz_name!r}") from exc
    hour, minute = (int(part) for part in hhmm.split(":"))
    now = datetime.now(tz)
    when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if when < now:
        when += timedelta(days=1)
    return int(when.timestamp())


def _cmd_search(args: argparse.Namespace) -> int:
    filters = SearchFilters(
        min_rating=args.min_rating,
        category=args.category,
        radius_km=args.radius_km,
        sort=args.sort,
        limit=args.limit,
    )
    places = search(
        args.query,
        near=args.near,
        filters=filters,
        locale=args.locale,
        country=args.country,
    )
    for place in places:
        cache.put(cid=place.cid, name=place.name, lat=place.lat, lng=place.lng, ftid=place.ftid, place_id=place.place_id)
    if args.json or args.json_pretty:
        _emit_json({"query": args.query, "returned": len(places), "results": [p.to_json() for p in places]}, args)
    else:
        print(format_search_table(places))
        _note("Details: `maps show <cid>`. Directions: `maps directions --to <cid>`. Tighten: --min-rating/--category/--sort.")
    return 0


def _resolve(cid: int, locale: str, country: str) -> Stop:
    """A place's identity from the cache (free) or a place-detail fetch (then cached)."""
    cached = cache.get(cid)
    if cached is not None:
        return cached
    detail = show(cid, locale=locale, country=country)
    cache.put(cid=detail.cid, name=detail.name, lat=detail.lat or 0.0, lng=detail.lng or 0.0, ftid=detail.ftid, place_id=detail.place_id)
    return Stop(name=detail.name, lat=detail.lat or 0.0, lng=detail.lng or 0.0, place_id=detail.place_id, ftid=detail.ftid)


def _cmd_directions(args: argparse.Namespace) -> int:
    if args.depart and args.arrive:
        return _fail("use either --depart or --arrive, not both")
    time_kind = "depart" if args.depart else "arrive" if args.arrive else None
    if time_kind is not None and args.mode != "transit":
        return _fail("--depart and --arrive apply to --mode transit")
    dest = _resolve(int(args.to), args.locale, args.country)
    origin = _resolve(int(args.from_cid), args.locale, args.country) if args.from_cid else None
    payload: dict[str, object] = {
        "directions_url": directions_url(dest, origin=origin, mode=args.mode),
        "mode": args.mode,
        "note": "Opens Maps at the exact places; omit --from to start from the phone.",
    }
    when = args.depart or args.arrive
    if args.steps or time_kind is not None:
        if origin is None:
            return _fail("--steps/--depart/--arrive need --from (an origin cid)")
        epoch = _next_epoch(when, args.tz) if when is not None else None
        leg = directions(
            (origin.lat, origin.lng),
            (dest.lat, dest.lng),
            mode=args.mode,
            locale=args.locale,
            country=args.country,
            time_kind=time_kind,
            epoch=epoch,
        )
        payload["leg"] = leg.to_json()
        if time_kind is not None and epoch is not None:
            payload[time_kind] = {"time": when, "tz": args.tz}
            payload["directions_url"] = transit_time_url(dest, origin, kind=time_kind, epoch=epoch)
    _emit(payload)
    return 0


def _cmd_route(args: argparse.Namespace) -> int:
    raw = json.loads(args.stops)
    if not isinstance(raw, list):
        return _fail("--stops must be a JSON array of {name, lat, lng, place_id?}")
    stops = [
        Stop(
            name=str(item["name"]),
            lat=float(item["lat"]),
            lng=float(item["lng"]),
            place_id=str(item["place_id"]) if "place_id" in item else None,
        )
        for item in raw
    ]
    _emit(
        {
            "route_url": route_url(stops, mode=args.mode),
            "stops": len(stops),
            "note": "One link opens the whole ordered route. Pass place_id per stop for named pins.",
        }
    )
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    detail = show(int(args.cid), locale=args.locale, country=args.country)
    cache.put(cid=detail.cid, name=detail.name, lat=detail.lat or 0.0, lng=detail.lng or 0.0, ftid=detail.ftid, place_id=detail.place_id)
    if args.json or args.json_pretty:
        _emit_json(detail.to_json(), args)
    else:
        print(format_place_detail(detail))
        _note(f"Directions: `maps directions --to {detail.cid}`.")
    return 0


def _cmd_itinerary(args: argparse.Namespace) -> int:
    cids = [int(part) for part in args.stops.split(",") if part]
    if len(cids) < 2:
        return _fail("--stops needs at least two cids, comma-separated")
    plan = itinerary(
        cids,
        mode=args.mode,
        start=args.start,
        dwell_min=args.dwell,
        optimize=args.optimize,
        locale=args.locale,
        country=args.country,
    )
    if args.json or args.json_pretty:
        _emit_json(plan.to_json(), args)
    else:
        print(format_itinerary(plan))
        _note("One route_url opens the whole day in Maps.")
    return 0


def _cmd_geocode(args: argparse.Namespace) -> int:
    places = search(
        args.address,
        near=None,
        filters=SearchFilters(limit=1),
        locale=args.locale,
        country=args.country,
    )
    if not places:
        return _fail(f"no match for address: {args.address}")
    top = places[0]
    _emit({"lat": top.lat, "lng": top.lng, "place_id": top.place_id, "cid": top.cid, "name": top.name})
    return 0


def _cmd_reverse(args: argparse.Namespace) -> int:
    lat, lng = _coord(args.coords)
    address = reverse(lat, lng, locale=args.locale, country=args.country)
    note = "Google's label for the point: a street address near a building, else a Plus Code."
    _emit({"lat": lat, "lng": lng, "address": address, "note": note})
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    checks = doctor(locale=args.locale, country=args.country)
    ok = all(value == "ok" for value in checks.values())
    note = "one check per RPC template" if ok else "a failing check names a drifted template; SETUP.md has the recapture steps"
    _emit({"status": "ok" if ok else "failing", "anchor": DOCTOR_ANCHOR_NAME, "checks": checks, "note": note})
    return 0 if ok else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="maps", description="Google Maps for vesta")
    sub = parser.add_subparsers(dest="command", required=True)

    # Shared as a parent parser so `--locale`/`--country` work after the subcommand, the shape an
    # agent naturally types (`maps search "..." --locale it-IT`).
    locale = argparse.ArgumentParser(add_help=False)
    locale.add_argument("--locale", default="en-US")
    locale.add_argument("--country", default="us")

    s = sub.add_parser("search", help="find places", parents=[locale])
    s.add_argument("query")
    s.add_argument("--near")
    s.add_argument("--min-rating", type=float, dest="min_rating")
    s.add_argument("--category")
    s.add_argument("--radius-km", type=float, dest="radius_km")
    s.add_argument("--sort", choices=("distance", "rating"))
    s.add_argument("--limit", type=int, default=20)
    _add_json_flags(s)
    s.set_defaults(func=_cmd_search)

    d = sub.add_parser("directions", help="build a directions deep link", parents=[locale])
    d.add_argument("--to", required=True, help="destination cid (from a search result)")
    d.add_argument("--from", dest="from_cid", help="origin cid (default: the phone's live location)")
    d.add_argument("--mode", default="driving", choices=("driving", "transit", "walking", "bicycling"))
    d.add_argument("--steps", action="store_true", help="also fetch duration and turn-by-turn steps (needs --from)")
    d.add_argument("--depart", help="transit: depart at HH:MM")
    d.add_argument("--arrive", help="transit: arrive by HH:MM")
    d.add_argument("--tz", default="UTC", help="IANA timezone for --depart/--arrive (e.g. Europe/Rome)")
    d.set_defaults(func=_cmd_directions)

    r = sub.add_parser("route", help="build a multi-stop route link")
    r.add_argument("--stops", required=True, help="JSON array of {name, lat, lng, place_id?}")
    r.add_argument("--mode", default="driving", choices=("driving", "transit", "walking", "bicycling"))
    r.set_defaults(func=_cmd_route)

    sh = sub.add_parser("show", help="full detail for one place by cid", parents=[locale])
    sh.add_argument("cid", help="the place's numeric cid (from a search result)")
    _add_json_flags(sh)
    sh.set_defaults(func=_cmd_show)

    it = sub.add_parser("itinerary", help="scheduled multi-stop day plan", parents=[locale])
    it.add_argument("--stops", required=True, help="comma-separated cids in order")
    it.add_argument("--mode", default="walking", choices=("driving", "transit", "walking", "bicycling"))
    it.add_argument("--start", default="10:00", help="start time HH:MM")
    it.add_argument("--dwell", type=int, default=30, help="minutes spent at each stop")
    it.add_argument("--optimize", action="store_true", help="reorder stops to cut travel")
    _add_json_flags(it)
    it.set_defaults(func=_cmd_itinerary)

    g = sub.add_parser("geocode", help="address -> coords", parents=[locale])
    g.add_argument("address")
    g.set_defaults(func=_cmd_geocode)

    rev = sub.add_parser("reverse", help="coords -> label", parents=[locale])
    rev.add_argument("coords", help="lat,lng")
    rev.set_defaults(func=_cmd_reverse)

    doc = sub.add_parser("doctor", help="health check: one probe per RPC template", parents=[locale])
    doc.set_defaults(func=_cmd_doctor)
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        result: int = args.func(args)
        return result
    except DriftError as exc:
        return _fail(f"maps schema drifted, recapture the pb template: {exc}")
    except BlockedError as exc:
        return _fail(f"temporarily blocked by Google, try later: {exc}")
    except httpx.HTTPError as exc:
        return _fail(f"network error: {exc}")
    except (ValueError, KeyError, TypeError) as exc:
        return _fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())
