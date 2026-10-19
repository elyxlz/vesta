"""The wake word rules, the wake behaviors, and the edge of the real detector."""

import pathlib as pl

import pytest
from voice.engine import behavior, detector, wake

WHOLE = "whole"
LIVE = "live"


def test_two_windows_in_a_row_at_the_threshold_make_one_hit() -> None:
    hits = wake.Hits()
    seen = []
    for score in (0.9, 0.9, 0.9, 0.9, 0.1, 0.6, 0.7):
        hits, hit = wake.observe(hits, score, 0.5)
        seen.append(hit)

    assert seen == [False, True, False, False, False, False, True]


def test_a_window_under_the_threshold_breaks_the_run() -> None:
    hits = wake.Hits()
    seen = []
    for score in (0.9, 0.2, 0.9, 0.9):
        hits, hit = wake.observe(hits, score, 0.5)
        seen.append(hit)

    assert seen == [False, False, False, True]


@pytest.mark.parametrize(
    ("waking", "active", "now", "open_until", "is_open"),
    [
        (False, False, 100.0, float("-inf"), True),
        (True, False, 100.0, float("-inf"), False),
        (True, True, 100.0, float("-inf"), True),
        (True, False, 100.0, 100.5, True),
        (True, False, 100.5, 100.5, False),
    ],
    ids=["wake word off", "waits for the phrase", "conversation active", "inside the window", "window over"],
)
def test_the_gate_is_open_while_the_rules_say(waking: bool, active: bool, now: float, open_until: float, is_open: bool) -> None:
    assert wake.gate_open(waking=waking, active=active, now=now, open_until=open_until) is is_open


@pytest.mark.parametrize(
    ("text", "kind", "left"),
    [
        ("Hey Aria, what time is it?", WHOLE, "what time is it?"),
        ("hey, aria. Book it", WHOLE, "Book it"),
        ("Hey Aria.", WHOLE, ""),
        ("hey arianna, hi", WHOLE, "hey arianna, hi"),
        ("What time is it, hey aria?", WHOLE, "What time is it, hey aria?"),
        ("hey", LIVE, ""),
        ("hey ar", LIVE, ""),
        ("hey aria what", LIVE, "what"),
        ("hey there", LIVE, "hey there"),
        ("hey", WHOLE, "hey"),
    ],
)
def test_the_phrase_at_the_start_is_removed(text: str, kind: str, left: str) -> None:
    assert wake.strip_phrase(text, "hey aria", live=kind == LIVE) == left


def test_each_phrase_has_its_own_model_file(tmp_path: pl.Path) -> None:
    assert wake.model_path(tmp_path, "Hey, Aria!") == tmp_path / "wake_words" / "hey_aria.onnx"


def test_the_wake_settings_exist_only_while_the_wake_word_is_on() -> None:
    assert behavior.wake_settings({}) is None
    assert behavior.wake_settings({"wake_word": True}) == behavior.WakeSettings(phrase="hey aria", threshold=0.5, follow_up_secs=5)
    assert behavior.wake_settings(
        {"wake_word": True, "wake_word_phrase": "hey vesta", "wake_word_threshold": 0.7, "wake_word_follow_up_secs": 0}
    ) == behavior.WakeSettings(phrase="hey vesta", threshold=0.7, follow_up_secs=0)


def test_a_missing_model_file_does_not_load(tmp_path: pl.Path) -> None:
    with pytest.raises(detector.DetectorError, match="no wake word model at"):
        detector.load(tmp_path / "hey_aria.onnx")


def test_a_file_that_is_not_a_model_does_not_load(tmp_path: pl.Path) -> None:
    model = tmp_path / "hey_aria.onnx"
    model.write_bytes(b"not a model")

    with pytest.raises(detector.DetectorError, match="did not load"):
        detector.load(model)
