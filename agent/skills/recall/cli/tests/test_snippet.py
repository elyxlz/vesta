import pathlib
import typing as tp

import pytest

from recall_cli import cli

Add = tp.Callable[[str, str, str], None]

# Both flanks are longer than SNIPPET_WINDOW_WORDS so a centered window trims (and elides) each side.
_LEAD = " ".join(f"lead{i:02d}" for i in range(30))
_TAIL = " ".join(f"tail{i:02d}" for i in range(30))


@pytest.mark.parametrize(
    "query,expected",
    [
        ("meeting notes", ["meeting", "notes"]),
        ('"exact phrase"', ["exact", "phrase"]),
        ("sched*", ["sched"]),
        ("cats OR dogs", ["cats", "dogs"]),
        ("meeting NOT cancelled", ["meeting", "cancelled"]),
        ("wifi AND password", ["wifi", "password"]),
        ("NEAR(a b)", ["a", "b"]),
    ],
)
def test_query_terms_strips_operators_and_punctuation(query: str, expected: list[str]) -> None:
    assert cli.query_terms(query) == expected


def test_window_centers_on_match_with_ellipses_both_sides() -> None:
    content = f"{_LEAD} SENTINEL {_TAIL}"
    result = cli.window(content, "sentinel")
    assert "SENTINEL" in result
    assert result.startswith(f"{cli.SNIPPET_ELLIPSIS} ")
    assert result.endswith(f" {cli.SNIPPET_ELLIPSIS}")
    assert len(result) < len(content)


def test_window_no_ellipsis_when_whole_message_fits() -> None:
    content = "the wifi password is hunter2"
    assert cli.window(content, "wifi") == content


def test_window_matches_prefix_query() -> None:
    content = f"{_LEAD} scheduling the standup {_TAIL}"
    result = cli.window(content, "sched*")
    assert "scheduling" in result


def test_window_falls_back_to_head_when_no_term_located() -> None:
    content = f"{_LEAD} {_TAIL}"
    result = cli.window(content, "nonexistentterm")
    assert result.startswith("lead00 lead01")
    assert result.endswith(f" {cli.SNIPPET_ELLIPSIS}")


def test_window_empty_content_is_returned_unchanged() -> None:
    assert cli.window("", "anything") == ""


def test_search_returns_full_content_by_default(events_db: tuple[pathlib.Path, Add]) -> None:
    path, add = events_db
    long_message = f"{_LEAD} the wifi password is hunter2 {_TAIL}"
    add("user", long_message, "2026-01-01T00:00:00")
    results = cli.search(path, "wifi", limit=20)
    assert len(results) == 1
    assert results[0]["content"] == long_message


def test_snippet_windows_search_results_around_the_match(events_db: tuple[pathlib.Path, Add]) -> None:
    path, add = events_db
    long_message = f"{_LEAD} the wifi password is hunter2 {_TAIL}"
    add("user", long_message, "2026-01-01T00:00:00")
    results = cli.search(path, "wifi", limit=20)
    windowed = cli.window(results[0]["content"], "wifi")
    assert "wifi password is hunter2" in windowed
    assert len(windowed) < len(long_message)


def test_search_ignores_non_conversational_events(events_db: tuple[pathlib.Path, Add]) -> None:
    path, add = events_db
    add("notification", "wifi outage alert", "2026-01-01T00:00:00")
    assert cli.search(path, "wifi", limit=20) == []
