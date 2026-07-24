"""Provider registry for STT/TTS backends."""

from .base import SttProvider, TtsProvider
from .deepgram import DeepgramStt
from .elevenlabs import ElevenLabsTts

_STT: dict[str, SttProvider] = {
    "deepgram": DeepgramStt(),
}

_TTS: dict[str, TtsProvider] = {
    "elevenlabs": ElevenLabsTts(),
}


def get_stt(name: str) -> SttProvider | None:
    return _STT[name] if name in _STT else None


def get_tts(name: str) -> TtsProvider | None:
    return _TTS[name] if name in _TTS else None


__all__ = ["SttProvider", "TtsProvider", "get_stt", "get_tts"]
