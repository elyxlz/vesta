"""Human-readable table rendering. The default output; `--json` gives the structured form.

Each search row shows the `cid`, which is how the agent references a place in a later command
(`directions --to <cid>`).
"""

from __future__ import annotations

from .models import Itinerary, Place, PlaceDetail


def _clip(text: str | None, width: int) -> str:
    value = text or ""
    return value if len(value) <= width else value[: width - 1] + "…"


def format_search_table(places: list[Place]) -> str:
    if not places:
        return "(no results)"
    rows = []
    for i, place in enumerate(places, 1):
        rating = f"{place.rating:>3}" if place.rating is not None else "  -"
        count = f"({place.review_count})" if place.review_count is not None else ""
        closed = "  closed now" if place.open_now is False else ""
        name, category, address = _clip(place.name, 34), _clip(place.category, 16), _clip(place.address, 30)
        rows.append(f"{i:2}. {name:<34} {rating} {count:<7} {category:<16} {address:<30}  cid:{place.cid}{closed}")
    return "\n".join(rows)


def format_place_detail(place: PlaceDetail) -> str:
    lines = [
        place.name,
        f"  {place.address}" if place.address else "",
        f"  {place.rating} stars" if place.rating is not None else "",
        f"  {place.category}" if place.category else "",
        f"  today: {place.hours_today}" if place.hours_today else "",
        f"  {place.phone}" if place.phone else "",
        f"  {place.website}" if place.website else "",
        f"  {place.links.place_url}" if place.links is not None else "",
        f"  cid:{place.cid}",
    ]
    return "\n".join(line for line in lines if line)


def format_itinerary(plan: Itinerary) -> str:
    lines = [
        f"  {stop.arrive}-{stop.leave}  {stop.place.name}" + ("  (closed at this time)" if stop.open_at_slot is False else "")
        for stop in plan.stops
    ]
    lines.append(f"  total: {plan.total_minutes} min")
    lines.append(f"  route: {plan.route_url}")
    return "\n".join(lines)
