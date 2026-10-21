"""The wake word rules: when the detector heard the phrase, when the session opens and closes the
STT stream (the gate), and the phrase at the start of what the user said.

The detector (detector.py) scores audio, and the session moves the audio and owns the stream.
This module decides, as pure functions of the state, one event, and the clock.
"""

import dataclasses as dc
import pathlib as pl
import re
import typing as tp

from . import frames
from .frames import MIC_SAMPLE_BYTES as SAMPLE_BYTES
from .frames import MIC_SAMPLE_RATE as SAMPLE_RATE

# The detector scores the newest window once for each frame of this length (80 ms).
FRAME_BYTES = 1280 * SAMPLE_BYTES
# The window the detector scores: its classifier reads 2 s of audio.
WINDOW_BYTES = 2 * SAMPLE_RATE * SAMPLE_BYTES
# The audio the session keeps while no audio goes to speech to text (1.5 s). It goes first when
# the gate opens, so the phrase and the words after it are complete.
PRE_ROLL_BYTES = 3 * SAMPLE_RATE * SAMPLE_BYTES // 2
# When the scores fall behind the mic, only the newest audio of this length (480 ms) is scored.
# Older audio only fills the window, so a hit is never late by more than this.
MAX_BEHIND_BYTES = 6 * FRAME_BYTES
# Windows in a row at or above the threshold that make one hit.
HIT_FRAMES = 2
# After a hit, the gate stays open at least this long, so the user can start to talk.
HEARD_SECS = 4.0
# After speech to text refuses a stream, the gate opens none for this long.
RETRY_SECS = 5.0
# Under the voice data directory: one `<phrase words joined by _>.onnx` for each phrase.
MODELS_DIR = "wake_words"


@dc.dataclass(frozen=True)
class Hits:
    # Windows in a row at or above the threshold.
    run: int = 0
    # False after a hit, until a window scores below the threshold: one phrase makes one hit.
    armed: bool = True


def observe(hits: Hits, score: float, threshold: float) -> tuple[Hits, bool]:
    """The next state for one scored window, and whether the window completes a hit."""
    if score < threshold:
        return Hits(), False
    if not hits.armed:
        return hits, False
    if hits.run + 1 >= HIT_FRAMES:
        return Hits(armed=False), True
    return Hits(run=hits.run + 1), False


def scores(*, window_bytes: int, behind_bytes: int) -> bool:
    """Whether the detector scores the window that one new frame completes: only a full window,
    and only one in the newest MAX_BEHIND_BYTES of the audio that waits."""
    return window_bytes >= WINDOW_BYTES and behind_bytes <= MAX_BEHIND_BYTES


# Where the STT stream of the session is: none, one that opens, or one that is open.
Stream = tp.Literal["closed", "opening", "open"]


@dc.dataclass(frozen=True)
class Gate:
    # With no activity, the gate stays open until this clock time: the window after a hit, after
    # speech, and after the last activity.
    open_until: float = float("-inf")
    # After a refused stream, no stream opens before this clock time.
    retry_at: float = float("-inf")
    # The conversation was active at the last step.
    active: bool = False
    # The client was told that the session waits for the phrase.
    waiting: bool = False


class GateSignal(tp.TypedDict):
    # `check` is any other event of the session. `speech` is live text from the stream, even
    # when it is only the phrase, which no turn sees.
    kind: tp.Literal["check", "speech", "hit", "opened"]


class Refused(tp.TypedDict):
    kind: tp.Literal["refused"]
    reason: tp.Literal["failed", "limit"]


GateEvent = GateSignal | Refused


class StreamAction(tp.TypedDict):
    type: tp.Literal["open_stream", "close_stream"]


GateAction = StreamAction | frames.WakeListening | frames.Error | frames.Ended

CHECK: GateSignal = {"kind": "check"}
OPEN_STREAM: StreamAction = {"type": "open_stream"}
CLOSE_STREAM: StreamAction = {"type": "close_stream"}


def _on_refused(gate: Gate, event: Refused, *, now: float) -> tuple[Gate, list[GateAction]]:
    """The gate tries again after RETRY_SECS. The client is told at the first refusal after a
    stream that opened."""
    told: list[GateAction] = []
    if gate.retry_at == float("-inf"):
        message = f"speech to text refused a stream ({event['reason']}); the session tries again in {RETRY_SECS:g} s"
        told = [{"type": "error", "message": message}]
    return dc.replace(gate, retry_at=now + RETRY_SECS), told


def gate_step(
    gate: Gate, event: GateEvent, *, follow_up_secs: float | None, active: bool, stream: Stream, now: float
) -> tuple[Gate, list[GateAction]]:
    """The gate after one event of the session, and what the session does about it.

    `follow_up_secs` is None while the wake word is off: the gate is always open, and a refused
    stream ends the session, which has no other way to hear. With it on, the gate is open while the
    conversation is `active` (the user talks, or a reply plays or waits to play) and until
    `open_until`. The window counts from the end of the activity, so the step after it extends it.
    """
    actions: list[GateAction] = []
    if event["kind"] == "refused":
        if follow_up_secs is None:
            return gate, [{"type": "ended", "reason": "stt_limit" if event["reason"] == "limit" else "stt_failed"}]
        gate, actions = _on_refused(gate, event, now=now)
    elif event["kind"] == "opened":
        gate = dc.replace(gate, retry_at=float("-inf"))
    follow_up = 0.0 if follow_up_secs is None else follow_up_secs
    if event["kind"] == "hit":
        gate = dc.replace(gate, open_until=max(gate.open_until, now + max(follow_up, HEARD_SECS)))
    elif event["kind"] == "speech" or active or gate.active:
        gate = dc.replace(gate, open_until=max(gate.open_until, now + follow_up))
    is_open = follow_up_secs is None or active or now < gate.open_until
    if is_open and stream == "closed" and now >= gate.retry_at:
        actions.append(OPEN_STREAM)
    elif not is_open and stream == "open":
        actions.append(CLOSE_STREAM)
    if gate.waiting == is_open:
        actions.append({"type": "wake_listening", "value": not is_open})
    return dc.replace(gate, active=active, waiting=not is_open), actions


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def model_path(data_dir: pl.Path, phrase: str) -> pl.Path:
    """`hey aria` -> <data_dir>/wake_words/hey_aria.onnx"""
    return data_dir / MODELS_DIR / f"{'_'.join(_words(phrase))}.onnx"


def strip_phrase(text: str, phrase: str, *, live: bool) -> str:
    """The text with the wake phrase at its start removed. Live text that is still only the start
    of the phrase (`hey ar`) is empty, so the phrase never shows as words for the agent."""
    phrase_words = _words(phrase)
    if not phrase_words:
        return text
    said = _words(text)
    still_the_phrase = 0 < len(said) <= len(phrase_words) and said[:-1] == phrase_words[: len(said) - 1]
    if live and still_the_phrase and phrase_words[len(said) - 1].startswith(said[-1]):
        return ""
    # The last word must end there: "hey aria's timer" keeps its words.
    pattern = r"^\W*" + r"\W+".join(re.escape(word) for word in phrase_words) + r"(?![\w'\u2019])\W*"
    return re.sub(pattern, "", text, count=1, flags=re.IGNORECASE)
