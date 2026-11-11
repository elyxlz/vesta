"""The behaviors: values that change how a session acts, the same for every provider.

They use the settings schema format of the providers, so the one check and the app's settings
card serve both. An open session reads them again each time the config file changes.
"""

import dataclasses as dc

from voice.settings import Domain, SettingDef, clamped

DEFAULT_WAKE_PHRASE = "hey aria"
DEFAULT_WAKE_THRESHOLD = 0.5
DEFAULT_FOLLOW_UP_SECS = 5
# 0 asks for the phrase before every line. A short window can close the stream at a pause in
# the middle of a sentence, so the user then says the phrase again.
MIN_FOLLOW_UP_SECS = 0
MAX_FOLLOW_UP_SECS = 60
MIN_WAKE_THRESHOLD = 0.05
MAX_WAKE_THRESHOLD = 0.95

BEHAVIOR_SCHEMA: list[SettingDef] = [
    {
        "key": "barge_in",
        "type": "bool",
        "label": "interrupt by voice",
        "description": "talk over a spoken reply to stop it; when off, a reply plays to its end or until you stop it on the device",
        "default": True,
    },
    {
        "key": "wake_word",
        "type": "bool",
        "label": "wake word",
        "description": "listen only after the wake phrase; until then no audio goes to speech to text",
        "default": False,
    },
    {
        "key": "wake_word_phrase",
        "type": "text",
        "label": "wake phrase",
        "description": "the phrase that starts a conversation; it needs a trained model, see the voice setup",
        "default": DEFAULT_WAKE_PHRASE,
    },
    {
        "key": "wake_word_threshold",
        "type": "number",
        "label": "wake sensitivity",
        "description": "the detector score that counts as the wake phrase; lower hears it more easily and wakes by mistake more often",
        "default": DEFAULT_WAKE_THRESHOLD,
        "min": MIN_WAKE_THRESHOLD,
        "max": MAX_WAKE_THRESHOLD,
        "step": 0.05,
    },
    {
        "key": "wake_word_follow_up_secs",
        "type": "number",
        "label": "follow-up window",
        "description": "after you or the agent stop talking, speech in this window continues the conversation with no wake phrase",
        "default": DEFAULT_FOLLOW_UP_SECS,
        "min": MIN_FOLLOW_UP_SECS,
        "max": MAX_FOLLOW_UP_SECS,
        "step": 1,
        "unit": "s",
    },
    {
        "key": "wake_word_keep_phrase",
        "type": "bool",
        "label": "keep wake phrase in transcript",
        "description": "show the wake phrase in what you said; when off it is removed from the start of your words",
        "default": False,
    },
]


@dc.dataclass(frozen=True)
class WakeSettings:
    phrase: str
    threshold: float
    follow_up_secs: float
    keep_phrase: bool = False


def barge_in_allowed(stored: Domain, session_can: bool | None) -> bool:
    """Barge-in has two inputs: the stored behavior is what the user wants, and `session_can` is
    what this session states it can do (None when it states nothing). Both must allow it."""
    wanted = stored["barge_in"] if "barge_in" in stored else True
    return wanted is not False and session_can is not False


def wake_phrase(stored: Domain) -> str:
    phrase = stored["wake_word_phrase"] if "wake_word_phrase" in stored else DEFAULT_WAKE_PHRASE
    return phrase if isinstance(phrase, str) and phrase.strip() else DEFAULT_WAKE_PHRASE


def wake_settings(stored: Domain, session_can: bool | None) -> WakeSettings | None:
    """The wake word settings, or None while the wake word is off. As for barge-in, `session_can`
    is what the session states (None when it states nothing), and False turns it off."""
    if "wake_word" not in stored or stored["wake_word"] is not True or session_can is False:
        return None
    return WakeSettings(
        phrase=wake_phrase(stored),
        threshold=clamped(stored, "wake_word_threshold", DEFAULT_WAKE_THRESHOLD, MIN_WAKE_THRESHOLD, MAX_WAKE_THRESHOLD),
        follow_up_secs=clamped(stored, "wake_word_follow_up_secs", DEFAULT_FOLLOW_UP_SECS, MIN_FOLLOW_UP_SECS, MAX_FOLLOW_UP_SECS),
        keep_phrase=stored.get("wake_word_keep_phrase") is True,
    )
