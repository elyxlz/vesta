"""The wake word rules: when the detector heard the phrase, when mic audio goes to speech to text,
and the phrase at the start of what the user said.

The detector (detector.py) scores audio, and the session moves the audio. This module decides.
"""

import dataclasses as dc
import pathlib as pl
import re

SAMPLE_RATE = 16000
SAMPLE_BYTES = 2
# The detector scores the newest window once for each frame of this length (80 ms).
FRAME_BYTES = 1280 * SAMPLE_BYTES
# The window the detector scores: its classifier reads 2 s of audio.
WINDOW_BYTES = 2 * SAMPLE_RATE * SAMPLE_BYTES
# The audio the session keeps while no audio goes to speech to text (1.5 s). It goes first when
# the gate opens, so the phrase and the words after it are complete.
PRE_ROLL_BYTES = 3 * SAMPLE_RATE * SAMPLE_BYTES // 2
# Windows in a row at or above the threshold that make one hit.
HIT_FRAMES = 2
# After a hit, the gate stays open at least this long, so the user can start to talk.
HEARD_SECS = 4.0
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


def gate_open(*, waking: bool, active: bool, now: float, open_until: float) -> bool:
    """Whether mic audio goes to speech to text. Always while the wake word is off. With it on:
    while the conversation is active (the user talks, or a reply plays or waits to play), and
    until `open_until`, the end of the window after a hit or after the last activity."""
    return not waking or active or now < open_until


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


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
    pattern = r"^\W*" + r"\W+".join(re.escape(word) for word in phrase_words) + r"\b\W*"
    return re.sub(pattern, "", text, count=1, flags=re.IGNORECASE)
