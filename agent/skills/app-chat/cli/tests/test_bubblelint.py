"""Mirrors telegram/whatsapp cli/bubblelint_test.go for the app-chat Python port."""

from app_chat_cli.bubblelint import bubble_lint_reason, text_after_full_stop


def test_bubble_lint_passes():
    # Short bubbles that end at their one mark (or carry none at all), and the
    # protected spans (urls, decimals, initialisms, abbreviations, ellipses)
    # whose dots must not read as full stops.
    for msg in [
        "nope, nothing",
        "on it",
        "yep",
        "checked both folders, nothing from them either",
        "running late, see you at 8",
        "done, anything else?",
        "one thought.",
        "meet at 8.30 by the door",
        "the W.A.S.T.E. system is down",
        "see https://example.com/a.b.c for the details",
        "call Dr. Smith back today",
        "meet on Jan. 5",
        "call Acme Inc. tomorrow",
        "it's on Oxford Ave. somewhere",
        "ask Jr. about it",
        "see vol. 3 for that",
        "wait... what",
        "hmm... ok",
        "it's in main.py",
        "check example.com later",
        # A multiline list is one send, each item a short thought: the line-leading
        # marker ("1.", "2)") must not read as a full stop.
        "1. eggs\n2. milk",
        "1. eggs\n2) milk",
        "here are steps:\n1. open\n2. run",
        "- eggs\n- milk",
    ]:
        assert bubble_lint_reason(msg) == "", msg


def test_bubble_lint_blocks():
    for msg in [
        "hey. ok",
        "done. anything else?",
        "i checked the first folder. then the second one. nothing in either.",
        "hey! how are you?",
        "nice! on it",
        "wait... what. ok",
        # An abbreviation that can end a thought would hide these walls, so none is protected.
        "the answer is no. anyway i tried",
        "eggs, milk, etc. also bread",
        "one sec. i'll check",
        "takes 20 min. i'll wait",
        # Only a line-leading marker is exempt: a single-line "1. x 2. y" has a mid-line
        # "2." that still reads as a wall, and a real full stop inside an item still trips.
        "1. Hello 2. Hi",
        "1. one thought. and another",
        (
            "so the thing about the deploy is that it kept timing out on the build step "
            "and i had to bump the worker memory and also tweak the cache config and re-run "
            "it twice and then clear the layer cache before it finally went green for us this afternoon"
        ),
    ]:
        assert bubble_lint_reason(msg) != "", msg


def test_text_after_full_stop():
    for msg, want in [
        ("one thought", False),
        ("one thought.", False),
        ("hey. ok", True),
        ("first. second.", True),
        ("first. second. third.", True),
        ("meet at 8.30 sharp", False),
        ("the U.K. office opens at 9", False),
        ("check https://a.com/x.y now", False),
        ("e.g. this should not count", False),
        ("wait... what", False),
        ("wait...", False),
        ("1. eggs\n2. milk", False),
        ("here are steps:\n1. open\n2. run", False),
        ("1.", False),
        ("1. one thought. and another", True),
        ("1. Hello 2. Hi", True),
    ]:
        assert text_after_full_stop(msg) is want, msg
