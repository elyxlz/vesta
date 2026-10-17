"""Provider registry for the three roles.

The providers that ship with the skill are listed here. `own.py` holds the providers of this box,
and the registry adds them. A name that two providers of one role share is a mistake that
`duplicate_names` reports, and every `voice` command refuses to run while one exists.
"""

from voice.config import Role
from voice.settings import Domain

from . import own
from .base import Judge, SttProvider, TtsProvider
from .deepgram import DeepgramStt
from .deepgram_tts import DeepgramTts
from .elevenlabs import ElevenLabsTts
from .elevenlabs_stt import ElevenLabsStt
from .typesafe import TypesafeJudge

_STT: dict[str, SttProvider] = {"deepgram": DeepgramStt(), "elevenlabs": ElevenLabsStt()}
_TTS: dict[str, TtsProvider] = {"deepgram": DeepgramTts(), "elevenlabs": ElevenLabsTts()}
_JUDGES: dict[str, Judge] = {"typesafe": TypesafeJudge()}

STT: dict[str, SttProvider] = {**own.STT, **_STT}
TTS: dict[str, TtsProvider] = {**own.TTS, **_TTS}
JUDGES: dict[str, Judge] = {**own.JUDGES, **_JUDGES}


def duplicate_names() -> list[str]:
    """`<role>: <name>` for each name that `own.py` uses and a shipped provider already has."""
    pairs = (("stt", own.STT, _STT), ("tts", own.TTS, _TTS), ("judge", own.JUDGES, _JUDGES))
    return [f"{role}: {name}" for role, mine, shipped in pairs for name in sorted(mine) if name in shipped]


def get_stt(name: str | None) -> SttProvider | None:
    return STT[name] if name is not None and name in STT else None


def get_tts(name: str | None) -> TtsProvider | None:
    return TTS[name] if name is not None and name in TTS else None


def get_judge(name: str | None) -> Judge | None:
    return JUDGES[name] if name is not None and name in JUDGES else None


def get(role: Role, name: str | None) -> SttProvider | TtsProvider | Judge | None:
    return {"stt": get_stt, "tts": get_tts, "judge": get_judge}[role](name)


def names(role: Role) -> list[str]:
    return sorted({"stt": STT, "tts": TTS, "judge": JUDGES}[role])


def selected_voice(provider: TtsProvider, entry: Domain) -> str:
    """The voice the provider speaks with: its stored voice setting, or the default of its schema."""
    key = provider.voice_setting
    if key in entry and isinstance(entry[key], str) and entry[key]:
        return str(entry[key])
    return next(str(d["default"]) for d in provider.settings_schema() if d["key"] == key)


__all__ = [
    "JUDGES",
    "STT",
    "TTS",
    "Judge",
    "SttProvider",
    "TtsProvider",
    "duplicate_names",
    "get",
    "get_judge",
    "get_stt",
    "get_tts",
    "names",
    "selected_voice",
]
