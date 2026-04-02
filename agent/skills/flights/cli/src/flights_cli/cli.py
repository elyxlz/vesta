"""Flights skill CLI — wraps fli (punitarani/fli) for Vesta.

Provides:
  flights search   — one-way or round-trip search on specific date(s) [Google Flights]
  flights dates    — find cheapest dates in a date range [Google Flights]
  flights cheapest — top cheapest options across multiple home airports [Google Flights]
  flights offer    — search bookable offers via Duffel API
  flights book     — book a Duffel offer
  flights orders   — list booked orders
  flights order    — get order details
  flights cancel   — cancel an order
  flights passenger — manage saved passenger profiles
"""

import argparse
import json
import sys
from datetime import datetime, timedelta


# Configure these to match your user's home airports.
# Example: London airports. Replace with your own.
HOME_AIRPORTS = ["LHR", "LGW", "STN", "LTN", "LCY"]

DEFAULT_CABIN = "ECONOMY"
DEFAULT_SORT = "CHEAPEST"
DEFAULT_STOPS = "ANY"


def _fmt_duration(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    return f"{h}h{m:02d}m"


def _fmt_datetime(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def _flight_to_dict(flight) -> dict:
    """Convert a FlightResult to a plain dict."""
    legs = []
    for leg in flight.legs:
        legs.append(
            {
                "airline": leg.airline.value,
                "flight_number": leg.flight_number,
                "from": leg.departure_airport.name,
                "to": leg.arrival_airport.name,
                "departs": _fmt_datetime(leg.departure_datetime),
                "arrives": _fmt_datetime(leg.arrival_datetime),
                "duration_min": leg.duration,
            }
        )
    return {
        "price_usd": round(flight.price, 2),
        "total_duration": _fmt_duration(flight.duration),
        "stops": flight.stops,
        "legs": legs,
    }


def _roundtrip_to_dict(outbound, inbound) -> dict:
    out = _flight_to_dict(outbound)
    ret = _flight_to_dict(inbound)
    return {
        "price_usd": round(outbound.price + inbound.price, 2),
        "outbound": out,
        "return": ret,
    }


def _search_flights(
    origin: str,
    destination: str,
    date: str,
    return_date: str | None = None,
    stops: str = DEFAULT_STOPS,
    cabin: str = DEFAULT_CABIN,
    sort: str = DEFAULT_SORT,
    max_results: int = 10,
) -> list[dict]:
    """Run a flight search for a single origin and return list of result dicts."""
    from fli.models import FlightSearchFilters, PassengerInfo
    from fli.core import build_flight_segments, resolve_airport, parse_max_stops, parse_cabin_class, parse_sort_by
    from fli.search import SearchFlights

    try:
        origin_ap = resolve_airport(origin)
        dest_ap = resolve_airport(destination)
        seat_type = parse_cabin_class(cabin)
        max_stops = parse_max_stops(stops)
        sort_by = parse_sort_by(sort)

        segments, trip_type = build_flight_segments(
            origin=origin_ap,
            destination=dest_ap,
            departure_date=date,
            return_date=return_date,
        )

        filters = FlightSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=segments,
            stops=max_stops,
            seat_type=seat_type,
            sort_by=sort_by,
        )

        results = SearchFlights().search(filters)
        if not results:
            return []

        out = []
        for r in results[:max_results]:
            if isinstance(r, tuple):
                out.append(_roundtrip_to_dict(r[0], r[1]))
            else:
                out.append(_flight_to_dict(r))
        return out

    except Exception as e:
        return [{"error": str(e), "origin": origin}]


def _search_dates(
    origin: str,
    destination: str,
    from_date: str,
    to_date: str,
    round_trip: bool = False,
    duration: int = 3,
    stops: str = DEFAULT_STOPS,
    cabin: str = DEFAULT_CABIN,
    max_results: int = 20,
) -> list[dict]:
    """Search cheapest dates for a single origin."""
    from fli.models import DateSearchFilters, PassengerInfo
    from fli.core import build_date_search_segments, resolve_airport, parse_max_stops, parse_cabin_class
    from fli.search import SearchDates

    try:
        origin_ap = resolve_airport(origin)
        dest_ap = resolve_airport(destination)
        seat_type = parse_cabin_class(cabin)
        max_stops = parse_max_stops(stops)

        segments, trip_type = build_date_search_segments(
            origin=origin_ap,
            destination=dest_ap,
            start_date=from_date,
            trip_duration=duration,
            is_round_trip=round_trip,
        )

        filters = DateSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=segments,
            stops=max_stops,
            seat_type=seat_type,
            from_date=from_date,
            to_date=to_date,
            duration=duration if round_trip else None,
        )

        results = SearchDates().search(filters)
        if not results:
            return []

        # Sort by price and limit
        results.sort(key=lambda x: x.price)
        out = []
        for r in results[:max_results]:
            if len(r.date) == 2:
                entry = {
                    "price_usd": round(r.price, 2),
                    "depart": r.date[0].strftime("%Y-%m-%d"),
                    "depart_day": r.date[0].strftime("%A"),
                    "return": r.date[1].strftime("%Y-%m-%d"),
                    "return_day": r.date[1].strftime("%A"),
                }
            else:
                entry = {
                    "price_usd": round(r.price, 2),
                    "depart": r.date[0].strftime("%Y-%m-%d"),
                    "depart_day": r.date[0].strftime("%A"),
                }
            out.append(entry)
        return out

    except Exception as e:
        return [{"error": str(e), "origin": origin}]


# ===========================================================================
# Google Flights commands
# ===========================================================================


def cmd_search(args):
    """flights search — search specific date(s)."""
    origins = args.origin if isinstance(args.origin, list) else [args.origin]

    all_results = []
    for origin in origins:
        results = _search_flights(
            origin=origin.upper(),
            destination=args.destination.upper(),
            date=args.date,
            return_date=getattr(args, "return_date", None),
            stops=args.stops,
            cabin=args.cabin,
            sort=args.sort,
            max_results=args.max_results,
        )
        for r in results:
            r["origin"] = origin.upper()
        all_results.extend(results)

    # If multiple origins and no errors, sort combined results by price
    if len(origins) > 1:
        valid = [r for r in all_results if "error" not in r]
        errors = [r for r in all_results if "error" in r]
        valid.sort(key=lambda x: x.get("price_usd", float("inf")))
        all_results = valid[: args.max_results] + errors

    print(json.dumps(all_results, indent=2))


def cmd_dates(args):
    """flights dates — cheapest dates in range."""
    origins = args.origin if isinstance(args.origin, list) else [args.origin]

    all_results = []
    for origin in origins:
        results = _search_dates(
            origin=origin.upper(),
            destination=args.destination.upper(),
            from_date=args.from_date,
            to_date=args.to_date,
            round_trip=args.round_trip,
            duration=args.duration,
            stops=args.stops,
            cabin=args.cabin,
            max_results=args.max_results,
        )
        for r in results:
            r["origin"] = origin.upper()
        all_results.extend(results)

    # Sort combined results by price
    if len(origins) > 1:
        valid = [r for r in all_results if "error" not in r]
        errors = [r for r in all_results if "error" in r]
        valid.sort(key=lambda x: x.get("price_usd", float("inf")))
        all_results = valid[: args.max_results] + errors

    print(json.dumps(all_results, indent=2))


def cmd_cheapest(args):
    """flights cheapest — try all home airports, return cheapest options."""
    origins = HOME_AIRPORTS

    from_date = args.from_date or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    to_date = args.to_date or (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")

    all_results = []
    for origin in origins:
        results = _search_dates(
            origin=origin,
            destination=args.destination.upper(),
            from_date=from_date,
            to_date=to_date,
            round_trip=args.round_trip,
            duration=args.duration,
            stops=DEFAULT_STOPS,
            cabin=DEFAULT_CABIN,
            max_results=5,  # top 5 per airport
        )
        for r in results:
            r["origin"] = origin
        all_results.extend(r for r in results if "error" not in r)

    all_results.sort(key=lambda x: x.get("price_usd", float("inf")))
    top = all_results[: args.top]

    print(json.dumps(top, indent=2))


# ===========================================================================
# Duffel API commands (booking)
# ===========================================================================


def _fmt_duffel_offer(offer: dict, idx: int) -> dict:
    """Format a Duffel offer into a readable dict."""
    slices_out = []
    for sl in offer.get("slices", []):
        segments = []
        for seg in sl.get("segments", []):
            carrier = (seg.get("operating_carrier") or seg.get("marketing_carrier")) or {}
            pax_list = seg.get("passengers") or []
            pax_info = pax_list[0] if pax_list else {}
            baggages = pax_info.get("baggages") or []
            bag_str = ", ".join(f"{b.get('type', '?')}:{b.get('quantity', 0)}" for b in baggages) if baggages else "none"

            aircraft_obj = seg.get("aircraft")
            segments.append(
                {
                    "airline": carrier.get("name", "?"),
                    "iata": carrier.get("iata_code", "?"),
                    "flight": f"{seg.get('marketing_carrier_flight_number') or seg.get('operating_carrier_flight_number') or '?'}",
                    "from": (seg.get("origin") or {}).get("iata_code", "?"),
                    "to": (seg.get("destination") or {}).get("iata_code", "?"),
                    "departs": seg.get("departing_at", "?"),
                    "arrives": seg.get("arriving_at", "?"),
                    "duration": seg.get("duration", "?"),
                    "aircraft": aircraft_obj.get("name", "?") if aircraft_obj else "?",
                    "bags": bag_str,
                }
            )
        slices_out.append(
            {
                "duration": sl.get("duration", "?"),
                "segments": segments,
            }
        )

    conditions = offer.get("conditions") or {}
    refund_info = conditions.get("refund_before_departure") or {}
    change_info = conditions.get("change_before_departure") or {}
    result = {
        "index": idx + 1,
        "offer_id": offer["id"],
        "airline": (offer.get("owner") or {}).get("name", "?"),
        "price": f"{offer.get('total_amount', '?')} {offer.get('total_currency', '?')}",
        "base": f"{offer.get('base_amount', '?')} {offer.get('base_currency', offer.get('total_currency', '?'))}",
        "tax": f"{offer.get('tax_amount', '?')} {offer.get('tax_currency', offer.get('total_currency', '?'))}",
        "expires_at": offer.get("expires_at", "?"),
        "slices": slices_out,
        "stops": sum(max(0, len(sl.get("segments", [])) - 1) for sl in offer.get("slices", [])),
        "refundable": refund_info.get("allowed", False),
        "changeable": change_info.get("allowed", False),
        "docs_required": offer.get("passenger_identity_documents_required", False),
    }
    return result


def cmd_offer(args):
    """flights offer — search bookable offers via Duffel."""
    from . import duffel

    slices = [
        {
            "origin": args.origin.upper(),
            "destination": args.destination.upper(),
            "departure_date": args.date,
        }
    ]

    if args.return_date:
        slices.append(
            {
                "origin": args.destination.upper(),
                "destination": args.origin.upper(),
                "departure_date": args.return_date,
            }
        )

    cabin = args.cabin.lower().replace("_", " ") if args.cabin != "ANY" else None
    passengers = [{"type": "adult"}] * args.passengers

    try:
        result = duffel.create_offer_request(
            slices=slices,
            passengers=passengers,
            cabin_class=cabin or "economy",
            max_connections=args.max_connections if args.max_connections >= 0 else None,
        )

        offers = result.get("offers", [])
        passenger_ids = [p["id"] for p in result.get("passengers", [])]

        # Sort by price
        offers.sort(key=lambda o: float(o.get("total_amount", "999999")))

        # Limit results
        offers = offers[: args.max_results]

        formatted = []
        for i, offer in enumerate(offers):
            formatted.append(_fmt_duffel_offer(offer, i))

        output = {
            "offer_request_id": result.get("id"),
            "passenger_ids": passenger_ids,
            "cabin_class": cabin or "economy",
            "offers_count": len(result.get("offers", [])),
            "showing": len(formatted),
            "offers": formatted,
        }
        print(json.dumps(output, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)


def cmd_book(args):
    """flights book — book a Duffel offer."""
    from . import duffel

    # Build passenger list
    passengers = []

    if args.profile:
        # Load from saved profile
        profile = duffel.get_profile(args.profile)
        profile["id"] = args.passenger_id
        passengers.append(profile)
    else:
        if not all([args.given_name, args.family_name, args.born_on, args.email, args.phone]):
            print(
                json.dumps(
                    {
                        "error": "Must provide --given-name, --family-name, --born-on, --email, --phone "
                        "OR --profile <name>. Use 'flights passenger save' to create a profile."
                    }
                ),
                file=sys.stderr,
            )
            sys.exit(1)

        pax = {
            "id": args.passenger_id,
            "given_name": args.given_name,
            "family_name": args.family_name,
            "title": args.title,
            "gender": args.gender,
            "born_on": args.born_on,
            "email": args.email,
            "phone_number": args.phone,
        }
        passengers.append(pax)

    try:
        order = duffel.create_order(
            offer_id=args.offer_id,
            passengers=passengers,
            payment_type="balance",
            order_type="instant",
            metadata={"booked_by": "vesta"},
        )

        output = {
            "status": "booked",
            "order_id": order["id"],
            "booking_reference": order.get("booking_reference", "?"),
            "total": f"{order.get('total_amount', '?')} {order.get('total_currency', '?')}",
            "live_mode": order.get("live_mode", False),
        }

        # Include slice info
        slices = []
        for sl in order.get("slices", []):
            segs = []
            for seg in sl.get("segments", []):
                carrier = seg.get("operating_carrier", {}) or seg.get("marketing_carrier", {})
                segs.append(
                    {
                        "flight": f"{carrier.get('iata_code', '?')}{seg.get('operating_carrier_flight_number', seg.get('marketing_carrier_flight_number', '?'))}",
                        "from": seg.get("origin", {}).get("iata_code", "?"),
                        "to": seg.get("destination", {}).get("iata_code", "?"),
                        "departs": seg.get("departing_at", "?"),
                        "arrives": seg.get("arriving_at", "?"),
                    }
                )
            slices.append({"segments": segs})
        output["slices"] = slices

        print(json.dumps(output, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)


def cmd_orders(args):
    """flights orders — list booked orders."""
    from . import duffel

    try:
        orders = duffel.list_orders(limit=args.limit)

        # list_orders returns a list (sometimes nested in pagination)
        if isinstance(orders, dict):
            # Paginated response
            order_list = orders if isinstance(orders, list) else [orders]
        else:
            order_list = orders

        formatted = []
        for order in order_list:
            entry = {
                "order_id": order["id"],
                "booking_reference": order.get("booking_reference", "?"),
                "total": f"{order.get('total_amount', '?')} {order.get('total_currency', '?')}",
                "created_at": order.get("created_at", "?"),
                "live_mode": order.get("live_mode", False),
            }
            # Summarize slices
            route_parts = []
            for sl in order.get("slices", []):
                origin = sl.get("origin", {}).get("iata_code", "?")
                dest = sl.get("destination", {}).get("iata_code", "?")
                dep = sl.get("segments", [{}])[0].get("departing_at", "?")[:10] if sl.get("segments") else "?"
                route_parts.append(f"{origin}→{dest} {dep}")
            entry["route"] = ", ".join(route_parts)
            formatted.append(entry)

        print(json.dumps(formatted, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)


def cmd_order(args):
    """flights order — get order details."""
    from . import duffel

    try:
        order = duffel.get_order(args.order_id)
        print(json.dumps(order, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)


def cmd_cancel(args):
    """flights cancel — cancel an order."""
    from . import duffel

    try:
        result = duffel.cancel_order(args.order_id, confirm=not args.no_confirm)
        output = {
            "status": "cancelled" if not args.no_confirm else "pending_confirmation",
            "cancellation_id": result.get("id", "?"),
            "refund_amount": result.get("refund_amount", "?"),
            "refund_currency": result.get("refund_currency", "?"),
            "order_id": result.get("order_id", args.order_id),
        }
        print(json.dumps(output, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)


def cmd_passenger(args):
    """flights passenger — manage saved passenger profiles."""
    from . import duffel

    if args.passenger_action == "save":
        if not all([args.given_name, args.family_name, args.born_on, args.email, args.phone]):
            print(json.dumps({"error": "Must provide --given-name, --family-name, --born-on, --email, --phone"}), file=sys.stderr)
            sys.exit(1)

        profile = {
            "given_name": args.given_name,
            "family_name": args.family_name,
            "title": args.title,
            "gender": args.gender,
            "born_on": args.born_on,
            "email": args.email,
            "phone_number": args.phone,
        }
        duffel.save_profile(args.name, profile)
        print(json.dumps({"status": "saved", "name": args.name, "profile": profile}, indent=2))

    elif args.passenger_action == "list":
        profiles = duffel.load_profiles()
        print(json.dumps(profiles, indent=2))

    elif args.passenger_action == "show":
        try:
            profile = duffel.get_profile(args.name)
            print(json.dumps({args.name: profile}, indent=2))
        except RuntimeError as e:
            print(json.dumps({"error": str(e)}, indent=2), file=sys.stderr)
            sys.exit(1)

    elif args.passenger_action == "delete":
        profiles = duffel.load_profiles()
        if args.name in profiles:
            del profiles[args.name]
            duffel.PROFILES_FILE.write_text(json.dumps(profiles, indent=2))
            print(json.dumps({"status": "deleted", "name": args.name}, indent=2))
        else:
            print(json.dumps({"error": f"Profile '{args.name}' not found"}, indent=2), file=sys.stderr)
            sys.exit(1)


# ===========================================================================
# Main parser
# ===========================================================================


def main():
    parser = argparse.ArgumentParser(
        prog="flights",
        description="Flight search (Google Flights) and booking (Duffel API). Output is JSON.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- search (Google Flights) ---
    p_search = sub.add_parser(
        "search",
        help="Search flights on a specific date via Google Flights (one-way or round-trip)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Search for flights on a specific date.\n\n"
            "Examples:\n"
            "  flights search JFK LAX 2026-04-15\n"
            "  flights search JFK,EWR LAX 2026-04-15 --return-date 2026-04-20\n"
            "  flights search JFK LAX 2026-05-01 --stops 0\n"
        ),
    )
    p_search.add_argument(
        "origin",
        type=lambda s: [x.strip().upper() for x in s.split(",")],
        help="Origin IATA code(s), comma-separated for multiple (e.g. JFK or JFK,EWR,LGA)",
    )
    p_search.add_argument("destination", help="Destination IATA code (e.g. LAX)")
    p_search.add_argument("date", help="Departure date YYYY-MM-DD")
    p_search.add_argument("--return-date", dest="return_date", default=None, help="Return date YYYY-MM-DD (makes it round-trip)")
    p_search.add_argument("--stops", default=DEFAULT_STOPS, help="Max stops: ANY, 0 (non-stop), 1, 2 (default: ANY)")
    p_search.add_argument("--cabin", default=DEFAULT_CABIN, help="Cabin class: ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST")
    p_search.add_argument("--sort", default=DEFAULT_SORT, help="Sort by: CHEAPEST, DURATION, DEPARTURE_TIME, ARRIVAL_TIME")
    p_search.add_argument("--max-results", type=int, default=10, dest="max_results", help="Max results to return per origin (default: 10)")
    p_search.set_defaults(func=cmd_search)

    # --- dates (Google Flights) ---
    p_dates = sub.add_parser(
        "dates",
        help="Find cheapest dates to fly in a date range",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Find cheapest departure dates across a date range.\n\n"
            "Examples:\n"
            "  flights dates JFK LAX --from 2026-04-01 --to 2026-05-31\n"
            "  flights dates JFK,EWR LAX --from 2026-04-01 --to 2026-06-30\n"
            "  flights dates JFK LAX --from 2026-05-01 --to 2026-07-01 --round-trip --duration 5\n"
        ),
    )
    p_dates.add_argument(
        "origin",
        type=lambda s: [x.strip().upper() for x in s.split(",")],
        help="Origin IATA code(s), comma-separated (e.g. JFK or JFK,EWR,LGA)",
    )
    p_dates.add_argument("destination", help="Destination IATA code")
    p_dates.add_argument(
        "--from",
        dest="from_date",
        default=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
        help="Start of date range YYYY-MM-DD (default: tomorrow)",
    )
    p_dates.add_argument(
        "--to",
        dest="to_date",
        default=(datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d"),
        help="End of date range YYYY-MM-DD (default: 60 days from now)",
    )
    p_dates.add_argument("--round-trip", action="store_true", dest="round_trip", help="Search round-trip dates")
    p_dates.add_argument("--duration", type=int, default=3, help="Trip duration in days for round-trip (default: 3)")
    p_dates.add_argument("--stops", default=DEFAULT_STOPS, help="Max stops: ANY, 0, 1, 2 (default: ANY)")
    p_dates.add_argument("--cabin", default=DEFAULT_CABIN, help="Cabin class (default: ECONOMY)")
    p_dates.add_argument("--max-results", type=int, default=20, dest="max_results", help="Max results (default: 20)")
    p_dates.set_defaults(func=cmd_dates)

    # --- cheapest (Google Flights) ---
    p_cheapest = sub.add_parser(
        "cheapest",
        help="Find absolute cheapest flights from home airports to a destination",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Search all HOME_AIRPORTS (configured in cli.py) and return\n"
            "the cheapest date options across the range.\n\n"
            "Examples:\n"
            "  flights cheapest LAX\n"
            "  flights cheapest LAX --from 2026-05-01 --to 2026-07-31\n"
            "  flights cheapest LAX --round-trip --duration 4 --top 15\n"
        ),
    )
    p_cheapest.add_argument("destination", help="Destination IATA code")
    p_cheapest.add_argument(
        "--from",
        dest="from_date",
        default=None,
        help="Start of date range YYYY-MM-DD (default: tomorrow)",
    )
    p_cheapest.add_argument(
        "--to",
        dest="to_date",
        default=None,
        help="End of date range YYYY-MM-DD (default: 60 days from now)",
    )
    p_cheapest.add_argument("--round-trip", action="store_true", dest="round_trip", help="Search round-trip dates")
    p_cheapest.add_argument("--duration", type=int, default=3, help="Trip duration in days for round-trip (default: 3)")
    p_cheapest.add_argument("--top", type=int, default=10, help="Number of cheapest options to return (default: 10)")
    p_cheapest.set_defaults(func=cmd_cheapest)

    # --- offer (Duffel search) ---
    p_offer = sub.add_parser(
        "offer",
        help="Search bookable offers via Duffel API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Search for bookable flight offers via the Duffel API.\n"
            "Returns offers with IDs that can be booked with 'flights book'.\n\n"
            "Examples:\n"
            "  flights offer JFK LAX 2026-04-16\n"
            "  flights offer JFK LAX 2026-05-01 --return-date 2026-05-05\n"
            "  flights offer JFK LAX 2026-06-01 --passengers 2\n"
        ),
    )
    p_offer.add_argument("origin", help="Origin IATA code (e.g. JFK)")
    p_offer.add_argument("destination", help="Destination IATA code (e.g. LAX)")
    p_offer.add_argument("date", help="Departure date YYYY-MM-DD")
    p_offer.add_argument("--return-date", dest="return_date", default=None, help="Return date YYYY-MM-DD (makes it round-trip)")
    p_offer.add_argument("--passengers", type=int, default=1, help="Number of adult passengers (default: 1)")
    p_offer.add_argument("--cabin", default="ECONOMY", help="Cabin: ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST, ANY (default: ECONOMY)")
    p_offer.add_argument(
        "--max-connections", type=int, default=-1, dest="max_connections", help="Max connections per slice (-1 = any, 0 = direct only)"
    )
    p_offer.add_argument("--max-results", type=int, default=10, dest="max_results", help="Max offers to show (default: 10)")
    p_offer.set_defaults(func=cmd_offer)

    # --- book (Duffel booking) ---
    p_book = sub.add_parser(
        "book",
        help="Book a Duffel offer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Book a flight using a Duffel offer ID from 'flights offer'.\n\n"
            "Examples:\n"
            "  flights book off_xxx --passenger-id pas_xxx --profile myprofile\n"
            "  flights book off_xxx --passenger-id pas_xxx \\\n"
            "    --given-name First --family-name Last --title mr --gender m \\\n"
            "    --born-on 1990-01-01 --email user@example.com --phone +1234567890\n"
        ),
    )
    p_book.add_argument("offer_id", help="Offer ID from 'flights offer' (off_...)")
    p_book.add_argument("--passenger-id", required=True, dest="passenger_id", help="Passenger ID from offer response (pas_...)")
    p_book.add_argument("--profile", default=None, help="Use saved passenger profile (e.g. 'myprofile')")
    p_book.add_argument("--given-name", dest="given_name", default=None)
    p_book.add_argument("--family-name", dest="family_name", default=None)
    p_book.add_argument("--title", default="mr", help="mr, mrs, ms, miss, dr (default: mr)")
    p_book.add_argument("--gender", default="m", help="m or f (default: m)")
    p_book.add_argument("--born-on", dest="born_on", default=None, help="Date of birth YYYY-MM-DD")
    p_book.add_argument("--email", default=None)
    p_book.add_argument("--phone", default=None, help="Phone with country code (e.g. +1234567890)")
    p_book.set_defaults(func=cmd_book)

    # --- orders ---
    p_orders = sub.add_parser("orders", help="List booked orders")
    p_orders.add_argument("--limit", type=int, default=20, help="Max orders to show (default: 20)")
    p_orders.set_defaults(func=cmd_orders)

    # --- order ---
    p_order = sub.add_parser("order", help="Get order details")
    p_order.add_argument("order_id", help="Order ID (ord_...)")
    p_order.set_defaults(func=cmd_order)

    # --- cancel ---
    p_cancel = sub.add_parser("cancel", help="Cancel an order")
    p_cancel.add_argument("order_id", help="Order ID to cancel (ord_...)")
    p_cancel.add_argument("--no-confirm", action="store_true", dest="no_confirm", help="Create cancellation without confirming (pending state)")
    p_cancel.set_defaults(func=cmd_cancel)

    # --- passenger ---
    p_passenger = sub.add_parser(
        "passenger",
        help="Manage saved passenger profiles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Save, list, show, or delete passenger profiles for quick booking.\n\n"
            "Examples:\n"
            "  flights passenger save myprofile --given-name First --family-name Last \\\n"
            "    --born-on 1990-01-01 --email user@example.com --phone +1234567890\n"
            "  flights passenger list\n"
            "  flights passenger show myprofile\n"
            "  flights passenger delete myprofile\n"
        ),
    )
    p_passenger.add_argument("passenger_action", choices=["save", "list", "show", "delete"], help="Action: save, list, show, delete")
    p_passenger.add_argument("name", nargs="?", default=None, help="Profile name (required for save/show/delete)")
    p_passenger.add_argument("--given-name", dest="given_name", default=None)
    p_passenger.add_argument("--family-name", dest="family_name", default=None)
    p_passenger.add_argument("--title", default="mr")
    p_passenger.add_argument("--gender", default="m")
    p_passenger.add_argument("--born-on", dest="born_on", default=None)
    p_passenger.add_argument("--email", default=None)
    p_passenger.add_argument("--phone", default=None)
    p_passenger.set_defaults(func=cmd_passenger)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
