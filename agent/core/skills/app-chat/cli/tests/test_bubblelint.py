"""Mirrors telegram/whatsapp cli/bubblelint_test.go for the app-chat Python port."""

from app_chat_cli.bubblelint import bubble_lint_reason, count_sentences


def test_bubble_lint_passes():
    # Short bubbles, one or two sentences, and protected spans (urls, decimals,
    # initialisms, abbreviations) whose dots must not read as sentence breaks.
    for msg in [
        "nope, nothing",
        "on it",
        "yep",
        "checked both folders, nothing from them either",
        "running late, see you at 8",
        "meet at 8.30 by the door",
        "the W.A.S.T.E. system is down",
        "see https://example.com/a.b.c for the details",
        "call Dr. Smith back today",
        "done. anything else?",
    ]:
        assert bubble_lint_reason(msg) == "", msg


def test_bubble_lint_blocks():
    for msg in [
        "i checked the first folder. then the second one. nothing in either.",
        (
            "so the thing about the deploy is that it kept timing out on the build step "
            "and i had to bump the worker memory and also tweak the cache config and re-run "
            "it twice and then clear the layer cache before it finally went green for us this afternoon"
        ),
    ]:
        assert bubble_lint_reason(msg) != "", msg


def test_count_sentences():
    for msg, want in [
        ("one thought", 0),
        ("one thought.", 1),
        ("first. second.", 2),
        ("first. second. third.", 3),
        ("meet at 8.30 sharp", 0),
        ("the U.K. office opens at 9", 0),
        ("check https://a.com/x.y now", 0),
        ("e.g. this should not count", 0),
    ]:
        assert count_sentences(msg) == want, msg
