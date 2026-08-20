"""`maps` command dispatch. JSON on stdout; errors as {"error": ...} on stderr, non-zero exit.

Stateless: every command takes durable Google ids or coordinates and stores nothing. The agent
keeps its own working set (trip files); see SKILL.md.
"""

from __future__ import annotations

import argparse
import json
import sys

from .client import BlockedError, DriftError, SearchFilters, directions, itinerary, reverse, search, show
from .links import Stop, directions_url, route_url
from .models import Place


def _emit(payload: dict[str, object]) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def _fail(message: str) -> int:
    json.dump({"error": message}, sys.stderr, ensure_ascii=False)
    sys.stderr.write("\n")
    return 1


def _coord(text: str) -> tuple[float, float]:
    lat, lng = text.split(",")
    return (float(lat), float(lng))


def _place_json(place: Place) -> dict[str, object]:
    return place.to_json()


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
    _emit(
        {
            "query": args.query,
            "returned": len(places),
            "results": [_place_json(p) for p in places],
            "note": "Route: `maps route --stops <json>`. Tighten: --min-rating/--category/--radius-km/--sort.",
        }
    )
    return 0


def _cmd_directions(args: argparse.Namespace) -> int:
    dest = _coord(args.dest)
    origin = _coord(args.origin) if args.origin else None
    payload: dict[str, object] = {
        "directions_url": directions_url(dest, origin=origin, mode=args.mode),
        "mode": args.mode,
        "note": "Opens Maps with the route; origin omitted uses the phone's live location.",
    }
    if args.steps:
        if origin is None:
            return _fail("directions --steps needs --from as lat,lng to measure the route")
        leg = directions(origin, dest, mode=args.mode, locale=args.locale, country=args.country)
        payload["leg"] = leg.to_json()
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
    payload = detail.to_json()
    payload["note"] = "Directions: `maps directions <lat>,<lng> --steps`. Route: `maps route`."
    _emit(payload)
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
    plan["note"] = "One route_url opens the whole day in Maps. open_at_slot is null until hours land."
    _emit(plan)
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
    places = search("coffee", near=None, filters=SearchFilters(limit=3), locale=args.locale, country=args.country)
    _emit({"status": "ok", "sample_results": len(places), "note": "search RPC responding"})
    return 0


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
    s.set_defaults(func=_cmd_search)

    d = sub.add_parser("directions", help="build a directions deep link", parents=[locale])
    d.add_argument("dest", help="destination as lat,lng")
    d.add_argument("--from", dest="origin", help="origin as lat,lng (default: live location)")
    d.add_argument("--mode", default="driving", choices=("driving", "transit", "walking", "bicycling"))
    d.add_argument("--steps", action="store_true", help="also fetch duration and turn-by-turn steps (needs --from)")
    d.set_defaults(func=_cmd_directions)

    r = sub.add_parser("route", help="build a multi-stop route link")
    r.add_argument("--stops", required=True, help="JSON array of {name, lat, lng, place_id?}")
    r.add_argument("--mode", default="driving", choices=("driving", "transit", "walking", "bicycling"))
    r.set_defaults(func=_cmd_route)

    sh = sub.add_parser("show", help="full detail for one place by cid", parents=[locale])
    sh.add_argument("cid", help="the place's numeric cid (from a search result)")
    sh.set_defaults(func=_cmd_show)

    it = sub.add_parser("itinerary", help="scheduled multi-stop day plan", parents=[locale])
    it.add_argument("--stops", required=True, help="comma-separated cids in order")
    it.add_argument("--mode", default="walking", choices=("driving", "transit", "walking", "bicycling"))
    it.add_argument("--start", default="10:00", help="start time HH:MM")
    it.add_argument("--dwell", type=int, default=30, help="minutes spent at each stop")
    it.add_argument("--optimize", action="store_true", help="reorder stops to cut travel")
    it.set_defaults(func=_cmd_itinerary)

    g = sub.add_parser("geocode", help="address -> coords", parents=[locale])
    g.add_argument("address")
    g.set_defaults(func=_cmd_geocode)

    rev = sub.add_parser("reverse", help="coords -> label", parents=[locale])
    rev.add_argument("coords", help="lat,lng")
    rev.set_defaults(func=_cmd_reverse)

    doc = sub.add_parser("doctor", help="drift canary / health check", parents=[locale])
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
    except (ValueError, KeyError) as exc:
        return _fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())
