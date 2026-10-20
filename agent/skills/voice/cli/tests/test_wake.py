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
        ("Hey Aria's timer, stop it", WHOLE, "Hey Aria's timer, stop it"),
    ],
)
def test_the_phrase_at_the_start_is_removed(text: str, kind: str, left: str) -> None:
    assert wake.strip_phrase(text, "hey aria", live=kind == LIVE) == left


def test_each_phrase_has_its_own_model_file(tmp_path: pl.Path) -> None:
    assert wake.model_path(tmp_path, "Hey, Aria!") == tmp_path / "wake_words" / "hey_aria.onnx"


def test_a_phrase_in_any_letters_has_a_model_file_and_is_removed(tmp_path: pl.Path) -> None:
    assert wake.model_path(tmp_path, "Hé Aria") == tmp_path / "wake_words" / "hé_aria.onnx"
    assert wake.strip_phrase("Hé Aria, bonjour", "hé aria", live=False) == "bonjour"


@pytest.mark.parametrize(
    ("window_bytes", "behind_bytes", "scored"),
    [
        (wake.WINDOW_BYTES - wake.FRAME_BYTES, 0, False),
        (wake.WINDOW_BYTES, 0, True),
        (wake.WINDOW_BYTES, wake.MAX_BEHIND_BYTES, True),
        (wake.WINDOW_BYTES, wake.MAX_BEHIND_BYTES + wake.FRAME_BYTES, False),
    ],
    ids=["window not full", "up to date", "a little behind", "too far behind"],
)
def test_only_full_windows_of_the_newest_audio_are_scored(window_bytes: int, behind_bytes: int, scored: bool) -> None:
    assert wake.scores(window_bytes=window_bytes, behind_bytes=behind_bytes) is scored


def test_the_wake_settings_exist_only_while_the_wake_word_is_on() -> None:
    assert behavior.wake_settings({}, None) is None
    assert behavior.wake_settings({"wake_word": True}, None) == behavior.WakeSettings(phrase="hey aria", threshold=0.5, follow_up_secs=5)
    assert behavior.wake_settings(
        {"wake_word": True, "wake_word_phrase": "hey vesta", "wake_word_threshold": 0.7, "wake_word_follow_up_secs": 9}, True
    ) == behavior.WakeSettings(phrase="hey vesta", threshold=0.7, follow_up_secs=9)


def test_a_session_that_states_no_wake_word_listens_with_none() -> None:
    assert behavior.wake_settings({"wake_word": True}, False) is None


def test_the_follow_up_window_is_never_shorter_than_the_minimum() -> None:
    settings = behavior.wake_settings({"wake_word": True, "wake_word_follow_up_secs": 0}, None)

    assert settings is not None
    assert settings.follow_up_secs == behavior.MIN_FOLLOW_UP_SECS


def test_a_missing_model_file_does_not_load(tmp_path: pl.Path) -> None:
    with pytest.raises(detector.DetectorError, match="no wake word model at"):
        detector.load(tmp_path / "hey_aria.onnx")


def test_a_file_that_is_not_a_model_does_not_load(tmp_path: pl.Path) -> None:
    model = tmp_path / "hey_aria.onnx"
    model.write_bytes(b"not a model")

    with pytest.raises(detector.DetectorError, match="did not load"):
        detector.load(model)
