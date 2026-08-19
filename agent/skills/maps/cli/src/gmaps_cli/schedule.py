"""Pure itinerary scheduler: lay out arrive/leave slots and flag closed stops. No IO.

Times are `HH:MM` strings in the user's frame; the caller converts place hours to that frame
before calling. `optimize_order` cuts total travel with a nearest-neighbour pass, which is
optimal enough for the handful of stops a day plan holds.
"""

from __future__ import annotations

from .models import ItineraryStop, Place


def _to_min(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _to_hhmm(total: int) -> str:
    total %= 24 * 60
    return f"{total // 60:02d}:{total % 60:02d}"


def _open_at(slot_min: int, window: tuple[str, str] | None) -> bool:
    if window is None:
        return True
    open_min, close_min = _to_min(window[0]), _to_min(window[1])
    if close_min <= open_min:  # closes after midnight
        close_min += 24 * 60
        if slot_min < open_min:
            slot_min += 24 * 60
    return open_min <= slot_min <= close_min


def schedule(
    stops: list[Place],
    legs_s: list[int],
    *,
    start: str,
    dwell_min: int,
    hours: list[tuple[str, str] | None] | None = None,
) -> list[ItineraryStop]:
    if len(legs_s) != max(len(stops) - 1, 0):
        raise ValueError("legs_s must have one entry per gap between stops")
    windows = hours if hours is not None else [None] * len(stops)
    if len(windows) != len(stops):
        raise ValueError("hours must have one entry per stop")
    out: list[ItineraryStop] = []
    clock = _to_min(start)
    for i, place in enumerate(stops):
        arrive = clock
        leave = arrive + dwell_min
        out.append(
            ItineraryStop(
                place=place,
                arrive=_to_hhmm(arrive),
                leave=_to_hhmm(leave),
                open_at_slot=_open_at(arrive, windows[i]),
            )
        )
        if i < len(legs_s):
            clock = leave + round(legs_s[i] / 60)
    return out


def optimize_order(matrix: list[list[int]]) -> list[int]:
    """Nearest-neighbour visit order over a duration matrix, starting from stop 0."""
    n = len(matrix)
    if n == 0:
        return []
    unvisited = set(range(1, n))
    order = [0]
    current = 0
    while unvisited:
        nxt = min(unvisited, key=lambda j: matrix[current][j])
        order.append(nxt)
        unvisited.discard(nxt)
        current = nxt
    return order
