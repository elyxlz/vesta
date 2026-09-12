from datetime import timedelta

import pytest
from flashcards_cli import commands
from flashcards_cli.db import parse_datetime
from flashcards_cli.settings import Settings, load_settings, set_setting

from .conftest import NOON


def _add(conn, deck="spanish", *pairs):
    items = [(front, back, "") for front, back in pairs] or [("hola", "hello", "")]
    return commands.cards_add(conn, deck, items, now=NOON)


def test_add_creates_the_deck_and_new_cards_are_due_at_once(conn):
    added = _add(conn, "spanish", ("hola", "hello"), ("adiós", "goodbye"))
    assert added["deck_created"] is True and added["added"] == 2
    again = _add(conn, "spanish", ("gracias", "thanks"))
    assert again["deck_created"] is False
    due = commands.due_cards(conn, Settings(), now=NOON)
    assert [card["front"] for card in due] == ["hola", "adiós", "gracias"]
    assert all(card["state"] == "new" for card in due)


def test_add_rejects_blank_sides(conn):
    with pytest.raises(ValueError):
        commands.cards_add(conn, "x", [("  ", "hello", "")], now=NOON)


def test_good_pushes_the_card_forward_and_again_keeps_it_close(conn):
    _add(conn, "spanish", ("hola", "hello"), ("adiós", "goodbye"))
    good = commands.review(conn, Settings(), 1, "good", now=NOON)
    assert good["state"] == "learning" and good["remaining"] == 1
    assert parse_datetime(good["due"]) == NOON + timedelta(minutes=10)
    later = commands.review(conn, Settings(), 1, "good", now=NOON + timedelta(minutes=10))
    assert later["state"] == "review"
    assert parse_datetime(later["due"]) - NOON >= timedelta(days=1)
    again = commands.review(conn, Settings(), 1, "again", now=parse_datetime(later["due"]))
    assert again["state"] == "relearning"
    assert parse_datetime(again["due"]) - parse_datetime(later["due"]) <= timedelta(minutes=10)
    assert commands.card_get(conn, 1)["reviews"] == 3


def test_next_returns_the_earliest_due_and_the_remaining_count(conn):
    _add(conn, "spanish", ("a", "1"), ("b", "2"), ("c", "3"))
    commands.review(conn, Settings(), 1, "good", now=NOON)
    commands.review(conn, Settings(), 2, "good", now=NOON)
    nxt = commands.next_card(conn, Settings(), now=NOON + timedelta(minutes=10))
    assert nxt is not None
    assert (nxt["id"], nxt["remaining"]) == (1, 3)
    assert commands.next_card(conn, Settings(), now=NOON, deck="nothing") is None


def test_new_cards_per_day_caps_what_is_offered(conn):
    _add(conn, "spanish", *((f"q{i}", f"a{i}") for i in range(5)))
    settings = Settings(new_cards_per_day=2)
    assert len(commands.due_cards(conn, settings, now=NOON)) == 2
    commands.review(conn, settings, 1, "easy", now=NOON)
    commands.review(conn, settings, 2, "easy", now=NOON)
    assert commands.due_cards(conn, settings, now=NOON + timedelta(minutes=1)) == []
    assert len(commands.due_cards(conn, settings, now=NOON + timedelta(days=1))) >= 2


def test_review_rejects_bad_ratings_and_missing_cards(conn):
    _add(conn)
    with pytest.raises(ValueError):
        commands.review(conn, Settings(), 1, "meh", now=NOON)
    with pytest.raises(ValueError):
        commands.review(conn, Settings(), 42, "good", now=NOON)


def test_suspend_hides_from_due_and_resume_brings_it_back(conn):
    _add(conn)
    assert commands.card_suspend(conn, 1, suspended=True, now=NOON)["suspended"] is True
    assert commands.due_cards(conn, Settings(), now=NOON) == []
    with pytest.raises(ValueError):
        commands.review(conn, Settings(), 1, "good", now=NOON)
    commands.card_suspend(conn, 1, suspended=False, now=NOON)
    assert len(commands.due_cards(conn, Settings(), now=NOON)) == 1


def test_delete_is_soft_and_get_still_resolves(conn):
    _add(conn)
    deleted = commands.card_delete(conn, 1, now=NOON)
    assert deleted["deleted"] is True
    assert commands.card_list(conn, deck=None) == []
    assert commands.card_get(conn, 1)["front"] == "hola"
    with pytest.raises(ValueError):
        commands.card_update(conn, 1, front="x", back=None, notes=None, deck=None, now=NOON)


def test_update_moves_a_card_between_decks(conn):
    _add(conn)
    moved = commands.card_update(conn, 1, front=None, back="hi", notes=None, deck="greetings", now=NOON)
    assert (moved["deck"], moved["back"]) == ("greetings", "hi")
    assert [deck["name"] for deck in commands.deck_list(conn, now=NOON)] == ["greetings", "spanish"]


def test_deck_update_refuses_a_name_another_live_deck_holds(conn):
    commands.cards_add(conn, "spanish", [("hola", "hello", "")], now=NOON)
    commands.cards_add(conn, "french", [("bonjour", "hello", "")], now=NOON)
    with pytest.raises(ValueError, match="a deck named 'french' already exists"):
        commands.deck_update(conn, "spanish", new_name="french", description=None, now=NOON)
    assert [deck["name"] for deck in commands.deck_list(conn, now=NOON)] == ["french", "spanish"]


def test_deck_delete_hides_its_cards_and_deck_update_renames(conn):
    _add(conn, "spanish", ("a", "1"), ("b", "2"))
    renamed = commands.deck_update(conn, "spanish", new_name="es", description="Spanish basics", now=NOON)
    assert (renamed["name"], renamed["description"], renamed["cards"]) == ("es", "Spanish basics", 2)
    assert commands.deck_delete(conn, "es", now=NOON) == {"deck": "es", "cards": 2, "deleted": True}
    assert commands.due_cards(conn, Settings(), now=NOON) == []
    with pytest.raises(ValueError):
        commands.deck_delete(conn, "es", now=NOON)


def test_stats_counts_states_due_and_retention(conn):
    _add(conn, "spanish", ("a", "1"), ("b", "2"), ("c", "3"))
    commands.review(conn, Settings(), 1, "again", now=NOON)
    commands.review(conn, Settings(), 2, "easy", now=NOON)
    stats = commands.stats(conn, Settings(), now=NOON + timedelta(minutes=2))
    assert (stats["cards"], stats["new"], stats["learning"], stats["review"]) == (3, 1, 1, 1)
    # The card rated again is back after its one-minute learning step, beside the untouched new card.
    assert stats["due_now"] == 2 and stats["reviews_today"] == 2 and stats["retention_30d"] == 0.5
    assert stats["decks"][0]["due"] == 1 and stats["next_due"] == "2026-03-02T12:02:00+00:00"


def test_settings_round_trip_validate_and_reach_the_scheduler(conn):
    assert load_settings(conn) == Settings()
    updated = set_setting(conn, "desired_retention", "0.8")
    assert updated.desired_retention == 0.8 and load_settings(conn).desired_retention == 0.8
    for name, value in (("desired_retention", "0.5"), ("active_hours", "9-21"), ("new_cards_per_day", "-1"), ("nope", "1")):
        with pytest.raises(ValueError):
            set_setting(conn, name, value)
    _add(conn)
    commands.review(conn, load_settings(conn), 1, "good", now=NOON)
    lax = commands.review(conn, Settings(desired_retention=0.8), 1, "good", now=NOON + timedelta(minutes=10))
    strict = commands.review(conn, Settings(desired_retention=0.99), 1, "good", now=NOON + timedelta(minutes=10))
    assert parse_datetime(lax["due"]) > parse_datetime(strict["due"])
