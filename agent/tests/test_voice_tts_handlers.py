"""The prepare/stream HTTP contract behind native-audio TTS playback (issue #466).

Drives the real aiohttp app and routes; the TTS provider and on-disk config are
faked at the edge so no ElevenLabs call or ~/.voice file is needed.
"""

from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from voice import handlers, server

CONFIGURED_TTS = {
    "stt": None,
    "tts": {"provider": "fake", "selected_voice_id": "v1", "credentials": {"fake": {"api_key": "k"}}},
}


def _fake_provider():
    provider = MagicMock()
    provider.premade_voices.return_value = [{"id": "v1"}]

    async def fake_speak(text, voice_id, creds, request, audio_format):
        return web.Response(body=text.encode(), headers={"Content-Type": "audio/mpeg"})

    provider.speak = fake_speak
    return provider


@pytest.fixture
def voice_app(monkeypatch):
    """A fresh voice app wired to a faked, configured TTS provider with an empty id store."""
    monkeypatch.setattr("voice.config.load", lambda data_dir: dict(CONFIGURED_TTS))
    monkeypatch.setattr("voice.providers.get_tts", lambda name: _fake_provider())
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
    monkeypatch.setattr("voice.config.load", lambda data_dir: {"stt": None, "tts": None})
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post("/tts/prepare", json={"text": "hello"})
        assert resp.status == 503
