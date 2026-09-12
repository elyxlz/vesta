"""Deck, card, review, and stats operations over one connection. Every CLI subcommand and HTTP
route calls one of these, so the two surfaces cannot drift."""

import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from fsrs import Card as FsrsCard
from fsrs import Rating, State

from .db import iso
from .format import rel_delta
from .settings import Settings, build_scheduler

RATINGS = {"again": Rating.Again, "hard": Rating.Hard, "good": Rating.Good, "easy": Rating.Easy}
RATING_NAMES = {rating: name for name, rating in RATINGS.items()}
STATE_NAMES = {State.Learning: "learning", State.Review: "review", State.Relearning: "relearning"}
RETENTION_WINDOW = timedelta(days=30)


class Deck(TypedDict):
    id: int
    name: str
    description: str
    cards: int
    new: int
    due: int
    created_at: str


class Card(TypedDict):
    id: int
    deck: str
    front: str
    back: str
    notes: str
    state: str
    due: str
    last_review: str | None
    stability: float | None
    difficulty: float | None
    reviews: int
    created_at: str
    suspended: bool
    deleted: bool


class NextCard(Card):
    remaining: int


class AddResult(TypedDict):
    deck: str
    deck_created: bool
    added: int
    ids: list[int]


class ReviewResult(TypedDict):
    id: int
    rating: str
    state: str
    due: str
    due_in: str
    stability: float | None
    difficulty: float | None
    remaining: int


class DeckDeleted(TypedDict):
    deck: str
    cards: int
    deleted: bool


class DueSummary(TypedDict):
    total: int
    decks: dict[str, int]


class Stats(TypedDict):
    cards: int
    new: int
    learning: int
    review: int
    suspended: int
    due_now: int
    next_due: str | None
    reviews_today: int
    retention_30d: float | None
    decks: list[Deck]


_CARD_SELECT = (
    "SELECT c.*, d.name AS deck, (SELECT COUNT(*) FROM reviews r WHERE r.card_id = c.id) AS reviews "
    "FROM cards c JOIN decks d ON d.id = c.deck_id"
)
# Deleting a deck marks every card in it deleted, so the card row alone decides liveness.
_LIVE = "c.deleted_at IS NULL"
_ACTIVE = f"{_LIVE} AND c.suspended_at IS NULL"
_DECK_SELECT = "SELECT d.name AS deck FROM cards c JOIN decks d ON d.id = c.deck_id"


def _card(row: sqlite3.Row) -> Card:
    fsrs = json.loads(row["fsrs"])
    return Card(
        id=row["id"],
        deck=row["deck"],
        front=row["front"],
        back=row["back"],
        notes=row["notes"],
        state="new" if row["last_review"] is None else STATE_NAMES[State(row["state"])],
        due=row["due"],
        last_review=row["last_review"],
        stability=fsrs["stability"],
        difficulty=fsrs["difficulty"],
        reviews=row["reviews"],
        created_at=row["created_at"],
        suspended=row["suspended_at"] is not None,
        deleted=row["deleted_at"] is not None,
    )


def _deck(row: sqlite3.Row) -> Deck:
    return Deck(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        cards=row["cards"],
        new=row["new"],
        due=row["due"],
        created_at=row["created_at"],
    )


def _deck_id(conn: sqlite3.Connection, name: str, *, create: bool, now: datetime) -> tuple[int, bool]:
    row = conn.execute("SELECT id FROM decks WHERE name = ? AND deleted_at IS NULL", (name,)).fetchone()
    if row is not None:
        return row["id"], False
    if not create:
        raise ValueError(f"no deck named {name!r}")
    cursor = conn.execute("INSERT INTO decks (name, created_at) VALUES (?, ?)", (name, iso(now)))
    if cursor.lastrowid is None:
        raise ValueError(f"could not create deck {name!r}")
    return cursor.lastrowid, True


def _deck_clause(deck: str | None) -> tuple[str, tuple[str, ...]]:
    return (" AND d.name = ?", (deck,)) if deck is not None else ("", ())


def _fetch_card(conn: sqlite3.Connection, card_id: int) -> sqlite3.Row:
    row = conn.execute(f"{_CARD_SELECT} WHERE c.id = ?", (card_id,)).fetchone()
    if row is None:
        raise ValueError(f"no card with id {card_id}")
    return row


def _day_start(now: datetime) -> datetime:
    """Local midnight, so a daily budget resets when the user's day does."""
    return now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)


def deck_list(conn: sqlite3.Connection, *, now: datetime) -> list[Deck]:
    rows = conn.execute(
        "SELECT d.id, d.name, d.description, d.created_at, COUNT(c.id) AS cards, "
        "COUNT(c.id) FILTER (WHERE c.suspended_at IS NULL AND c.last_review IS NULL) AS new, "
        "COUNT(c.id) FILTER (WHERE c.suspended_at IS NULL AND c.last_review IS NOT NULL AND c.due <= ?) AS due "
        "FROM decks d LEFT JOIN cards c ON c.deck_id = d.id AND c.deleted_at IS NULL "
        "WHERE d.deleted_at IS NULL GROUP BY d.id ORDER BY d.name",
        (iso(now),),
    )
    return [_deck(row) for row in rows]


def deck_update(conn: sqlite3.Connection, name: str, *, new_name: str | None, description: str | None, now: datetime) -> Deck:
    deck_id, _ = _deck_id(conn, name, create=False, now=now)
    if new_name is not None and new_name != name:
        if conn.execute("SELECT 1 FROM decks WHERE name = ? AND deleted_at IS NULL", (new_name,)).fetchone() is not None:
            raise ValueError(f"a deck named {new_name!r} already exists")
        conn.execute("UPDATE decks SET name = ? WHERE id = ?", (new_name, deck_id))
    if description is not None:
        conn.execute("UPDATE decks SET description = ? WHERE id = ?", (description, deck_id))
    conn.commit()
    return next(deck for deck in deck_list(conn, now=now) if deck["id"] == deck_id)


def deck_delete(conn: sqlite3.Connection, name: str, *, now: datetime) -> DeckDeleted:
    deck_id, _ = _deck_id(conn, name, create=False, now=now)
    cards = conn.execute("SELECT COUNT(*) FROM cards WHERE deck_id = ? AND deleted_at IS NULL", (deck_id,)).fetchone()[0]
    conn.execute("UPDATE cards SET deleted_at = ? WHERE deck_id = ? AND deleted_at IS NULL", (iso(now), deck_id))
    conn.execute("UPDATE decks SET deleted_at = ? WHERE id = ?", (iso(now), deck_id))
    conn.commit()
    return DeckDeleted(deck=name, cards=cards, deleted=True)


def cards_add(conn: sqlite3.Connection, deck: str, items: list[tuple[str, str, str]], *, now: datetime) -> AddResult:
    """Adds (front, back, notes) triples to a deck, creating the deck when it does not exist."""
    if not items:
        raise ValueError("nothing to add")
    for front, back, _ in items:
        if not front.strip() or not back.strip():
            raise ValueError("every card needs a non-empty front and back")
    deck_id, created = _deck_id(conn, deck, create=True, now=now)
    fsrs = FsrsCard(due=now.astimezone(UTC))
    ids = []
    for front, back, notes in items:
        cursor = conn.execute(
            "INSERT INTO cards (deck_id, front, back, notes, fsrs, state, due, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (deck_id, front.strip(), back.strip(), notes.strip(), fsrs.to_json(), int(fsrs.state), iso(now), iso(now)),
        )
        if cursor.lastrowid is not None:
            ids.append(cursor.lastrowid)
    conn.commit()
    return AddResult(deck=deck, deck_created=created, added=len(ids), ids=ids)


def card_get(conn: sqlite3.Connection, card_id: int) -> Card:
    return _card(_fetch_card(conn, card_id))


def card_list(conn: sqlite3.Connection, *, deck: str | None) -> list[Card]:
    clause, params = _deck_clause(deck)
    rows = conn.execute(f"{_CARD_SELECT} WHERE {_LIVE}{clause} ORDER BY c.due, c.id", params)
    return [_card(row) for row in rows]


def _require_live(conn: sqlite3.Connection, card_id: int) -> sqlite3.Row:
    row = _fetch_card(conn, card_id)
    if row["deleted_at"] is not None:
        raise ValueError(f"card {card_id} is deleted")
    return row


def card_update(
    conn: sqlite3.Connection,
    card_id: int,
    *,
    front: str | None,
    back: str | None,
    notes: str | None,
    deck: str | None,
    now: datetime,
) -> Card:
    _require_live(conn, card_id)
    text_fields = (("front", front), ("back", back), ("notes", notes))
    changes: list[tuple[str, str | int]] = [(column, value.strip()) for column, value in text_fields if value is not None]
    if any(not value for column, value in changes if column != "notes"):
        raise ValueError("front and back cannot be empty")
    if deck is not None:
        deck_id, _ = _deck_id(conn, deck, create=True, now=now)
        changes.append(("deck_id", deck_id))
    if not changes:
        raise ValueError("nothing to update: pass --front, --back, --notes, or --deck")
    for column, value in changes:
        conn.execute(f"UPDATE cards SET {column} = ? WHERE id = ?", (value, card_id))
    conn.commit()
    return card_get(conn, card_id)


def card_delete(conn: sqlite3.Connection, card_id: int, *, now: datetime) -> Card:
    _require_live(conn, card_id)
    conn.execute("UPDATE cards SET deleted_at = ? WHERE id = ?", (iso(now), card_id))
    conn.commit()
    return card_get(conn, card_id)


def card_suspend(conn: sqlite3.Connection, card_id: int, *, suspended: bool, now: datetime) -> Card:
    _require_live(conn, card_id)
    conn.execute("UPDATE cards SET suspended_at = ? WHERE id = ?", (iso(now) if suspended else None, card_id))
    conn.commit()
    return card_get(conn, card_id)


def _new_card_budget(conn: sqlite3.Connection, settings: Settings, *, now: datetime) -> int:
    introduced = conn.execute(
        "SELECT COUNT(*) FROM (SELECT card_id, MIN(reviewed_at) AS first FROM reviews GROUP BY card_id) WHERE first >= ?",
        (iso(_day_start(now)),),
    ).fetchone()[0]
    return max(0, settings.new_cards_per_day - introduced)


def _due_rows(
    conn: sqlite3.Connection, settings: Settings, *, now: datetime, deck: str | None, select: str, limit: int | None = None
) -> list[sqlite3.Row]:
    """Rows to ask now: every reviewed card past its due instant, then new cards up to today's budget."""
    clause, params = _deck_clause(deck)
    reviewed = conn.execute(
        f"{select} WHERE {_ACTIVE} AND c.last_review IS NOT NULL AND c.due <= ?{clause} ORDER BY c.due, c.id LIMIT ?",
        (iso(now), *params, -1 if limit is None else limit),
    ).fetchall()
    budget = _new_card_budget(conn, settings, now=now)
    if limit is not None:
        budget = max(0, min(budget, limit - len(reviewed)))
    fresh = conn.execute(f"{select} WHERE {_ACTIVE} AND c.last_review IS NULL{clause} ORDER BY c.created_at, c.id LIMIT ?", (*params, budget))
    return reviewed + fresh.fetchall()


def due_cards(conn: sqlite3.Connection, settings: Settings, *, now: datetime, deck: str | None = None, limit: int | None = None) -> list[Card]:
    return [_card(row) for row in _due_rows(conn, settings, now=now, deck=deck, select=_CARD_SELECT, limit=limit)]


def _due_decks(conn: sqlite3.Connection, settings: Settings, *, now: datetime, deck: str | None = None) -> list[str]:
    """The deck of every card due now: the due set without card bodies, for counting."""
    return [row["deck"] for row in _due_rows(conn, settings, now=now, deck=deck, select=_DECK_SELECT)]


def due_summary(conn: sqlite3.Connection, settings: Settings, *, now: datetime) -> DueSummary:
    decks = Counter(_due_decks(conn, settings, now=now))
    return DueSummary(total=decks.total(), decks=dict(decks))


def next_card(conn: sqlite3.Connection, settings: Settings, *, now: datetime, deck: str | None = None) -> NextCard | None:
    head = due_cards(conn, settings, now=now, deck=deck, limit=1)
    if not head:
        return None
    return NextCard(**head[0], remaining=len(_due_decks(conn, settings, now=now, deck=deck)))


def review(
    conn: sqlite3.Connection, settings: Settings, card_id: int, rating_name: str, *, now: datetime, seconds: int | None = None
) -> ReviewResult:
    if rating_name not in RATINGS:
        raise ValueError(f"rating must be one of {', '.join(RATINGS)}, got {rating_name!r}")
    row = _require_live(conn, card_id)
    if row["suspended_at"] is not None:
        raise ValueError(f"card {card_id} is suspended; resume it first")
    when = now.astimezone(UTC)
    updated, log = build_scheduler(settings).review_card(
        FsrsCard.from_json(row["fsrs"]), RATINGS[rating_name], review_datetime=when, review_duration=None if seconds is None else seconds * 1000
    )
    conn.execute(
        "UPDATE cards SET fsrs = ?, state = ?, due = ?, last_review = ? WHERE id = ?",
        (updated.to_json(), int(updated.state), iso(updated.due), iso(when), card_id),
    )
    conn.execute(
        "INSERT INTO reviews (card_id, rating, reviewed_at, duration_secs, log) VALUES (?, ?, ?, ?, ?)",
        (card_id, int(RATINGS[rating_name]), iso(when), seconds, log.to_json()),
    )
    conn.commit()
    return ReviewResult(
        id=card_id,
        rating=rating_name,
        state=STATE_NAMES[updated.state],
        due=iso(updated.due),
        due_in=rel_delta(updated.due - when),
        stability=updated.stability,
        difficulty=updated.difficulty,
        remaining=len(_due_decks(conn, settings, now=now)),
    )


def stats(conn: sqlite3.Connection, settings: Settings, *, now: datetime) -> Stats:
    counts = conn.execute(
        "SELECT COUNT(*) AS cards, IFNULL(SUM(c.last_review IS NULL), 0) AS new, "
        "IFNULL(SUM(c.last_review IS NOT NULL AND c.state IN (?, ?)), 0) AS learning, "
        "IFNULL(SUM(c.state = ?), 0) AS review, IFNULL(SUM(c.suspended_at IS NOT NULL), 0) AS suspended "
        f"FROM cards c WHERE {_LIVE}",
        (int(State.Learning), int(State.Relearning), int(State.Review)),
    ).fetchone()
    upcoming = conn.execute(
        f"SELECT MIN(c.due) FROM cards c WHERE {_ACTIVE} AND c.last_review IS NOT NULL AND c.due > ?", (iso(now),)
    ).fetchone()[0]
    waiting_new = conn.execute(f"SELECT COUNT(*) FROM cards c WHERE {_ACTIVE} AND c.last_review IS NULL").fetchone()[0]
    # New cards past today's budget become due when the budget resets at local midnight.
    tomorrow = iso(_day_start(now) + timedelta(days=1)) if waiting_new else None
    reviews_today = conn.execute("SELECT COUNT(*) FROM reviews WHERE reviewed_at >= ?", (iso(_day_start(now)),)).fetchone()[0]
    recent = conn.execute(
        "SELECT COUNT(*) AS total, IFNULL(SUM(rating != ?), 0) AS recalled FROM reviews WHERE reviewed_at >= ?",
        (int(Rating.Again), iso(now - RETENTION_WINDOW)),
    ).fetchone()
    due = due_summary(conn, settings, now=now)["total"]
    return Stats(
        cards=counts["cards"],
        new=counts["new"],
        learning=counts["learning"],
        review=counts["review"],
        suspended=counts["suspended"],
        due_now=due,
        next_due=iso(now) if due else min((instant for instant in (upcoming, tomorrow) if instant is not None), default=None),
        reviews_today=reviews_today,
        retention_30d=round(recent["recalled"] / recent["total"], 3) if recent["total"] else None,
        decks=deck_list(conn, now=now),
    )
