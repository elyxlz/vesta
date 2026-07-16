"""The TTS `format` param selects the audio encoding the backend returns.

`mp3` (the app's <audio> element) stays the default; `pcm` returns raw 16 kHz signed-16 LE PCM,
the frame format a phone-call consumer plays straight into a live call. Both map to an ElevenLabs
`output_format` and a Content-Type; an unknown format is a 400 before any upstream request.
"""

import asyncio

from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from voice.providers.elevenlabs import AUDIO_FORMATS, ElevenLabsTts


def test_audio_formats_cover_mp3_and_pcm() -> None:
    assert AUDIO_FORMATS["mp3"] == ("mp3_22050_32", "audio/mpeg")
    output_format, content_type = AUDIO_FORMATS["pcm"]
    assert output_format == "pcm_16000"
    assert content_type == "audio/l16;rate=16000"


def test_speak_rejects_unknown_format_without_upstream_call() -> None:
    # An unsupported format short-circuits to 400 before any network request, so no creds are
    # needed and no upstream is contacted.
    provider = ElevenLabsTts()
    request = make_mocked_request("POST", "/tts/speak")
    response = asyncio.run(provider.speak("hi", "voice-id", {"api_key": "k"}, request, "flac"))
    assert isinstance(response, web.Response)
    assert response.status == 400
