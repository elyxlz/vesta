"""The prepare/stream HTTP contract behind native-audio TTS playback (issue #466).

Drives the real aiohttp app and routes; the TTS provider and on-disk config are
faked at the edge so no ElevenLabs call or ~/.voice file is needed.
"""

import typing as tp

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer
from voice import handlers, server
from voice.settings import Domain, SettingDef

CONFIGURED_TTS = {
    "stt": None,
    "tts": {"provider": "fake", "selected_voice_id": "v1", "credentials": {"fake": {"api_key": "k"}}},
    "judge": None,
    "behavior": None,
}
UNCONFIGURED = {"stt": None, "tts": None, "judge": None, "behavior": None}


class FakeTts:
    """A TTS provider whose audio is the text itself."""

    name = "fake"
    needs_key = True
    voice_setting = "selected_voice_id"
    formats = frozenset({"mp3_22050", "pcm_16000"})

    async def synthesize(
        self, text: str, _voice: str, _audio_format: str, _creds: dict[str, str], _settings: Domain, _http: aiohttp.ClientSession
    ) -> tp.AsyncIterator[bytes]:
        yield text.encode()

    def settings_schema(self) -> list[SettingDef]:
        return [{"key": "selected_voice_id", "type": "select", "default": "v1", "options": [{"value": "v1", "label": "V1"}]}]


@pytest.fixture
def voice_app(monkeypatch):
    """A fresh voice app wired to a faked, configured TTS provider with an empty id store."""
    monkeypatch.setattr("voice.config.load", lambda data_dir: dict(CONFIGURED_TTS))
    monkeypatch.setattr("voice.providers.get_tts", lambda name: FakeTts())
    handlers._PENDING_TTS.clear()
    return server.create_app()


@pytest.mark.anyio
async def test_prepare_then_stream_returns_the_audio(voice_app):
    async with TestClient(TestServer(voice_app)) as client:
        prepared = await client.post("/tts/prepare", json={"text": "hello world"})
        assert prepared.status == 200
        tts_id = (await prepared.json())["id"]

        streamed = await client.get(f"/tts/stream/{tts_id}")
        assert streamed.status == 200
        assert streamed.headers["Content-Type"] == "audio/mpeg"
        assert await streamed.text() == "hello world"


@pytest.mark.anyio
async def test_prepare_rejects_empty_text(voice_app):
    async with TestClient(TestServer(voice_app)) as client:
        resp = await client.post("/tts/prepare", json={"text": "   "})
        assert resp.status == 400


@pytest.mark.anyio
async def test_stream_unknown_id_is_404(voice_app):
    async with TestClient(TestServer(voice_app)) as client:
        resp = await client.get("/tts/stream/does-not-exist")
        assert resp.status == 404


@pytest.mark.anyio
async def test_prepare_when_tts_unconfigured_is_503(monkeypatch):
    monkeypatch.setattr("voice.config.load", lambda data_dir: dict(UNCONFIGURED))
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post("/tts/prepare", json={"text": "hello"})
        assert resp.status == 503
