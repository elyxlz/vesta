"""Compact text tables for the CLI, and the relative-time words every envelope carries."""

from datetime import datetime, timedelta

from .db import parse_datetime


def rel_delta(delta: timedelta) -> str:
    """A duration as one coarse unit: 45m, 3h, 2d, 3w."""
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 5400:
        return f"{max(seconds // 60, 1)}m"
    if seconds < 129600:
        return f"{round(seconds / 3600)}h"
    if seconds < 1209600:
        return f"{round(seconds / 86400)}d"
    return f"{round(seconds / 604800)}w"


def rel_time(instant: str | None, now: datetime) -> str:
    """An instant relative to now: 'in 3h', '2d ago', 'now' at or before now for a card just added."""
    if instant is None:
        return "-"
    when = parse_datetime(instant)
    if when > now:
        return f"in {rel_delta(when - now)}"
    return "now" if now - when < timedelta(minutes=1) else f"{rel_delta(now - when)} ago"


def _trunc(text: str, width: int) -> str:
    flat = " ".join(text.split()) or "-"
    return flat if len(flat) <= width else flat[: width - 3] + "..."


def _table(header: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(cell) for cell in column) for column in zip(header, *rows, strict=True)]
    lines = [header, *rows]
    return "\n".join("  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip() for line in lines)


def format_cards(cards: list[dict[str, str | int | float | bool | None]], now: datetime) -> str:
    if not cards:
        return "no cards"
    rows = [
        [str(card["id"]), _trunc(str(card["deck"]), 16), str(card["state"]), rel_time(str(card["due"]), now), _trunc(str(card["front"]), 60)]
        for card in cards
    ]
    return _table(["id", "deck", "state", "due", "front"], rows)


def format_decks(decks: list[dict[str, str | int]]) -> str:
    if not decks:
        return "no decks"
    rows = [[str(deck["name"]), str(deck["cards"]), str(deck["new"]), str(deck["due"]), _trunc(str(deck["description"]), 50)] for deck in decks]
    return _table(["deck", "cards", "new", "due", "description"], rows)
