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


NOW = 100.0
FOLLOW_UP = 5.0
NEVER = float("-inf")
WAITING = {"type": "wake_listening", "value": True}
LISTENING = {"type": "wake_listening", "value": False}
OPEN = {"type": "open_stream"}
CLOSE = {"type": "close_stream"}
CHECK: wake.GateEvent = {"kind": "check"}
REFUSED: wake.GateEvent = {"kind": "refused", "reason": "limit"}
TOLD_REFUSED = {"type": "error", "message": "speech to text refused a stream (limit); the session tries again in 5 s"}

GATE_ROWS = [
    ("wake word off: the stream opens", wake.Gate(), CHECK, None, False, "closed", wake.Gate(), [OPEN]),
    (
        "wake word off: a refusal ends the session",
        wake.Gate(),
        REFUSED,
        None,
        False,
        "closed",
        wake.Gate(),
        [{"type": "ended", "reason": "stt_limit"}],
    ),
    ("waits for the phrase", wake.Gate(), CHECK, FOLLOW_UP, False, "closed", wake.Gate(waiting=True), [WAITING]),
    (
        "a hit opens the gate for at least HEARD_SECS",
        wake.Gate(waiting=True),
        {"kind": "hit"},
        2.0,
        False,
        "closed",
        wake.Gate(open_until=NOW + wake.HEARD_SECS, heard_until=NOW + wake.HEARD_SECS),
        [OPEN, LISTENING],
    ),
    (
        "a stream that opens is not opened again",
        wake.Gate(open_until=NOW + 1),
        CHECK,
        FOLLOW_UP,
        False,
        "opening",
        wake.Gate(open_until=NOW + 1),
        [],
    ),
    (
        "activity keeps the gate open",
        wake.Gate(),
        CHECK,
        FOLLOW_UP,
        True,
        "open",
        wake.Gate(open_until=NOW + FOLLOW_UP, active=True),
        [],
    ),
    (
        "the window counts from the end of the activity",
        wake.Gate(open_until=NOW - 1, active=True),
        CHECK,
        FOLLOW_UP,
        False,
        "open",
        wake.Gate(open_until=NOW + FOLLOW_UP),
        [],
    ),
    (
        "speech that is only the phrase keeps the gate open",
        wake.Gate(open_until=NOW + 1),
        {"kind": "speech"},
        FOLLOW_UP,
        False,
        "open",
        wake.Gate(open_until=NOW + FOLLOW_UP),
        [],
    ),
    (
        "the window is over",
        wake.Gate(open_until=NOW),
        CHECK,
        FOLLOW_UP,
        False,
        "open",
        wake.Gate(open_until=NOW, waiting=True),
        [CLOSE, WAITING],
    ),
    (
        "the first refusal is told, and the gate waits",
        wake.Gate(open_until=NOW + 1),
        REFUSED,
        FOLLOW_UP,
        False,
        "closed",
        wake.Gate(open_until=NOW + 1, retry_at=NOW + wake.RETRY_SECS),
        [TOLD_REFUSED],
    ),
    (
        "a refusal in a row is not told again",
        wake.Gate(open_until=NOW + 1, retry_at=NOW),
        REFUSED,
        FOLLOW_UP,
        False,
        "closed",
        wake.Gate(open_until=NOW + 1, retry_at=NOW + wake.RETRY_SECS),
        [],
    ),
    (
        "the gate opens again after the wait",
        wake.Gate(open_until=NOW + 1, retry_at=NOW),
        CHECK,
        FOLLOW_UP,
        False,
        "closed",
        wake.Gate(open_until=NOW + 1, retry_at=NOW),
        [OPEN],
    ),
    (
        "a stream that opens ends the wait",
        wake.Gate(open_until=NOW + 1, retry_at=NOW + 1),
        {"kind": "opened"},
        FOLLOW_UP,
        False,
        "open",
        wake.Gate(open_until=NOW + 1, retry_at=NEVER),
        [],
    ),
]


PLAYING_ROWS = [
    (
        "a reply that plays closes the gate to everything but the phrase",
        wake.Gate(open_until=NOW + 1),
        CHECK,
        FOLLOW_UP,
        False,
        "open",
        wake.Gate(open_until=NOW + FOLLOW_UP, playing=True, waiting=True),
        [CLOSE, WAITING],
    ),
    (
        "a hit while a reply plays opens the gate",
        wake.Gate(open_until=NOW + 1, playing=True, waiting=True),
        {"kind": "hit"},
        FOLLOW_UP,
        False,
        "closed",
        wake.Gate(open_until=NOW + FOLLOW_UP, heard_until=NOW + FOLLOW_UP, playing=True),
        [OPEN, LISTENING],
    ),
    (
        "the user who talks keeps the gate open while a reply plays",
        wake.Gate(),
        CHECK,
        FOLLOW_UP,
        True,
        "open",
        wake.Gate(open_until=NOW + FOLLOW_UP, active=True, playing=True),
        [],
    ),
]


@pytest.mark.parametrize(
    ("name", "gate", "event", "follow_up_secs", "active", "stream", "after", "actions"),
    PLAYING_ROWS,
    ids=[row[0] for row in PLAYING_ROWS],
)
def test_the_gate_waits_for_the_phrase_while_a_reply_plays(
    name: str,
    gate: wake.Gate,
    event: wake.GateEvent,
    follow_up_secs: float | None,
    active: bool,
    stream: wake.Stream,
    after: wake.Gate,
    actions: list[wake.GateAction],
) -> None:
    got = wake.gate_step(gate, event, follow_up_secs=follow_up_secs, active=active, stream=stream, now=NOW, playing=True)
    assert got == (after, actions)


def test_the_window_opens_when_the_reply_ends() -> None:
    gate, _ = wake.gate_step(wake.Gate(), CHECK, follow_up_secs=FOLLOW_UP, active=False, stream="closed", now=NOW, playing=True)
    gate, actions = wake.gate_step(gate, CHECK, follow_up_secs=FOLLOW_UP, active=False, stream="closed", now=NOW + 3, playing=False)
    assert OPEN in actions and LISTENING in actions
    assert gate.open_until == NOW + 3 + FOLLOW_UP


@pytest.mark.parametrize(
    ("name", "gate", "event", "follow_up_secs", "active", "stream", "after", "actions"), GATE_ROWS, ids=[row[0] for row in GATE_ROWS]
)
def test_the_gate_steps_as_the_rules_say(
    name: str,
    gate: wake.Gate,
    event: wake.GateEvent,
    follow_up_secs: float | None,
    active: bool,
    stream: wake.Stream,
    after: wake.Gate,
    actions: list[wake.GateAction],
) -> None:
    assert wake.gate_step(gate, event, follow_up_secs=follow_up_secs, active=active, stream=stream, now=NOW) == (after, actions)


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
    settings = behavior.wake_settings({"wake_word": True, "wake_word_follow_up_secs": -3}, None)

    assert settings is not None
    assert settings.follow_up_secs == behavior.MIN_FOLLOW_UP_SECS


def test_a_zero_follow_up_window_asks_for_the_phrase_every_time() -> None:
    settings = behavior.wake_settings({"wake_word": True, "wake_word_follow_up_secs": 0}, None)

    assert settings is not None
    assert settings.follow_up_secs == 0


def test_the_phrase_is_kept_in_the_transcript_only_when_asked() -> None:
    kept = behavior.wake_settings({"wake_word": True, "wake_word_keep_phrase": True}, None)
    dropped = behavior.wake_settings({"wake_word": True}, None)

    assert kept is not None and kept.keep_phrase
    assert dropped is not None and not dropped.keep_phrase


def test_a_missing_model_file_does_not_load(tmp_path: pl.Path) -> None:
    with pytest.raises(detector.DetectorError, match="no wake word model at"):
        detector.load(tmp_path / "hey_aria.onnx")


def test_a_file_that_is_not_a_model_does_not_load(tmp_path: pl.Path) -> None:
    model = tmp_path / "hey_aria.onnx"
    model.write_bytes(b"not a model")

    with pytest.raises(detector.DetectorError, match="did not load"):
        detector.load(model)
