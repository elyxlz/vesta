"""Provider registry for STT/TTS backends."""

from .base import SttProvider, TtsProvider
from .deepgram import DeepgramStt
from .elevenlabs import ElevenLabsTts

_STT = {
    "deepgram": DeepgramStt(),
}

_TTS = {
    "elevenlabs": ElevenLabsTts(),
}


def get_stt(name: str) -> SttProvider | None:
    return _STT.get(name)  # type: ignore[return-value]


def get_tts(name: str) -> TtsProvider | None:
    return _TTS.get(name)  # type: ignore[return-value]


__all__ = ["SttProvider", "TtsProvider", "get_stt", "get_tts"]
