"""The HTTP routes: status and settings for the app, and the stock app's audio routes."""

import asyncio
import pathlib as pl
import typing as tp

import aiohttp
import pytest
import voice.config as vc
from aiohttp.test_utils import TestClient
from voice import providers

from .fakes import FRAME_TIMEOUT_SECS, FakeStt, FakeTts, next_frame, voice_service


@pytest.fixture
def tts(monkeypatch: pytest.MonkeyPatch, tmp_path: pl.Path) -> FakeTts:
    fake = FakeTts()
    monkeypatch.setitem(providers.TTS, "fake", fake)
    vc.connect(tmp_path, "tts", "fake", {})
    return fake


def serve(tmp_path: pl.Path, scenario: tp.Callable[[TestClient], tp.Awaitable[None]]) -> None:
    async def run() -> None:
        async with voice_service(tmp_path) as client:
            await scenario(client)

    asyncio.run(run())


def test_speak_streams_the_audio_of_the_selected_provider(tmp_path: pl.Path, tts: FakeTts) -> None:
    async def scenario(client: TestClient) -> None:
        async with client.post("/tts/speak", json={"text": "Hi"}) as resp:
            assert resp.status == 200
            assert resp.headers["Content-Type"] == "audio/mpeg"
            assert await resp.read() == b"auHidioHi"
        async with client.post("/tts/speak", json={"text": "Hi", "format": "pcm"}) as resp:
            assert resp.headers["Content-Type"] == "audio/l16;rate=16000"

    serve(tmp_path, scenario)
    assert tts.spoken == [("Hi", "v-default", "mp3_22050"), ("Hi", "v-default", "pcm_16000")]


def test_speak_rejects_an_unknown_format_before_any_synthesis(tmp_path: pl.Path, tts: FakeTts) -> None:
    async def scenario(client: TestClient) -> None:
        async with client.post("/tts/speak", json={"text": "Hi", "format": "flac"}) as resp:
            assert resp.status == 400

    serve(tmp_path, scenario)
    assert tts.spoken == []


def test_speak_rejects_a_format_that_the_selected_provider_cannot_make(tmp_path: pl.Path, tts: FakeTts) -> None:
    tts.formats = frozenset({"mp3_22050"})

    async def scenario(client: TestClient) -> None:
        async with client.post("/tts/speak", json={"text": "Hi", "format": "pcm"}) as resp:
            assert resp.status == 400

    serve(tmp_path, scenario)


def test_a_refused_synthesis_gets_an_error_status(tmp_path: pl.Path, tts: FakeTts) -> None:
    tts.fail = True

    async def scenario(client: TestClient) -> None:
        async with client.post("/tts/speak", json={"text": "Hi"}) as resp:
            assert resp.status == 502
            assert await resp.json() == {"error": "the fake refused the synthesis"}

    serve(tmp_path, scenario)


def test_a_prepared_id_streams_its_text_and_an_unknown_id_is_404(tmp_path: pl.Path, tts: FakeTts) -> None:
    async def scenario(client: TestClient) -> None:
        async with client.post("/tts/prepare", json={"text": "Later"}) as resp:
            prepared = await resp.json()
        async with client.get(f"/tts/stream/{prepared['id']}") as resp:
            assert await resp.read() == b"auLaterdioLater"
        async with client.get("/tts/stream/nobody") as resp:
            assert resp.status == 404

    serve(tmp_path, scenario)


def test_prepare_rejects_empty_text(tmp_path: pl.Path, tts: FakeTts) -> None:
    async def scenario(client: TestClient) -> None:
        async with client.post("/tts/prepare", json={"text": "   "}) as resp:
            assert resp.status == 400

    serve(tmp_path, scenario)


def test_prepare_when_tts_has_no_provider_is_503(tmp_path: pl.Path) -> None:
    async def scenario(client: TestClient) -> None:
        async with client.post("/tts/prepare", json={"text": "hello"}) as resp:
            assert resp.status == 503

    serve(tmp_path, scenario)


def test_the_tts_status_shows_the_voices_of_the_selected_provider_and_the_users_own(tmp_path: pl.Path, tts: FakeTts) -> None:
    vc.add_custom_voice(tmp_path, "v-mine", "Mine")

    async def scenario(client: TestClient) -> None:
        async with client.get("/tts/status") as resp:
            status = await resp.json()

        assert (status["configured"], status["provider"], status["enabled"], status["connected"]) == (True, "fake", True, ["fake"])
        voice = status["settings"][0]
        assert (voice["key"], voice["value"]) == ("fake_voice", "v-default")
        assert [option["value"] for option in voice["options"]] == ["v-default", "v-other", "v-mine"]
        assert voice["options"][2] == {"value": "v-mine", "label": "Mine", "custom": True}

    serve(tmp_path, scenario)


def test_set_voice_stores_the_voice_under_the_key_of_the_selected_provider(tmp_path: pl.Path, tts: FakeTts) -> None:
    async def scenario(client: TestClient) -> None:
        async with client.post("/tts/set-voice", json={"voice_id": "v-other"}) as resp:
            assert await resp.json() == {"ok": True}
        async with client.post("/tts/set-voice", json={"voice_id": "v-nobody"}) as resp:
            assert resp.status == 400

    serve(tmp_path, scenario)
    assert vc.load(tmp_path)["tts"]["fake_voice"] == "v-other"


def test_use_selects_a_connected_provider_and_returns_its_status(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(providers.STT, "fake", FakeStt())
    vc.connect(tmp_path, "stt", "fake", {})
    vc.connect(tmp_path, "stt", "deepgram", {"api_key": "k"})

    async def scenario(client: TestClient) -> None:
        async with client.post("/stt/use", json={"provider": "fake"}) as resp:
            status = await resp.json()
        assert (status["provider"], status["connected"]) == ("fake", ["deepgram", "fake"])
        assert [setting["key"] for setting in status["settings"]] == ["address"]
        async with client.post("/stt/use", json={"provider": "elevenlabs"}) as resp:
            assert resp.status == 400

    serve(tmp_path, scenario)


def test_the_status_of_a_role_with_no_provider_lists_nothing(tmp_path: pl.Path) -> None:
    async def scenario(client: TestClient) -> None:
        async with client.get("/stt/status") as resp:
            assert await resp.json() == {"configured": False, "provider": None, "connected": []}

    serve(tmp_path, scenario)


def test_the_generic_set_route_checks_a_value_against_the_schema(tmp_path: pl.Path) -> None:
    vc.connect(tmp_path, "stt", "deepgram", {"api_key": "k"})

    async def scenario(client: TestClient) -> None:
        async with client.post("/stt/set", json={"key": "multi_language", "value": True}) as resp:
            status = await resp.json()
        assert next(s["value"] for s in status["settings"] if s["key"] == "multi_language") is True
        for body in ({"key": "eot_threshold", "value": 2}, {"key": "made_up", "value": 1}, {"key": "eot_threshold", "value": [1]}):
            async with client.post("/stt/set", json=body) as resp:
                assert resp.status == 400
        async with client.post("/stt/set-eot", json={"timeout_ms": 3000}) as resp:
            assert resp.status == 200

    serve(tmp_path, scenario)
    assert vc.load(tmp_path)["stt"]["eot_timeout_ms"] == 3000


def test_a_behavior_is_read_and_set_like_a_provider_setting(tmp_path: pl.Path) -> None:
    async def scenario(client: TestClient) -> None:
        async with client.get("/behavior/status") as resp:
            before = await resp.json()
        assert [(s["key"], s["type"], s["value"]) for s in before["settings"]] == [("barge_in", "bool", True)]
        async with client.post("/behavior/set", json={"key": "barge_in", "value": False}) as resp:
            assert (await resp.json())["settings"][0]["value"] is False
        async with client.post("/behavior/set", json={"key": "barge_in", "value": "sometimes"}) as resp:
            assert resp.status == 400

    serve(tmp_path, scenario)


def test_turning_a_role_on_needs_a_selected_provider(tmp_path: pl.Path) -> None:
    async def scenario(client: TestClient) -> None:
        async with client.post("/tts/set-enabled", json={"value": True}) as resp:
            assert resp.status == 400
        async with client.post("/tts/set-enabled", json={"value": False}) as resp:
            assert await resp.json() == {"ok": True}

    serve(tmp_path, scenario)


def test_the_reply_hint_is_the_hint_of_the_selected_provider_while_tts_is_on(tmp_path: pl.Path, tts: FakeTts) -> None:
    tts.reply_hint = "the fake sings each word"

    async def hint(client: TestClient) -> str:
        async with client.get("/tts/reply-hint") as resp:
            return (await resp.json())["reply_hint"]

    async def scenario(client: TestClient) -> None:
        assert await hint(client) == "the fake sings each word"
        vc.set_enabled(tmp_path, "tts", False)
        assert await hint(client) == ""

    serve(tmp_path, scenario)


def test_the_reply_hint_is_empty_when_tts_has_no_provider(tmp_path: pl.Path) -> None:
    async def scenario(client: TestClient) -> None:
        async with client.get("/tts/reply-hint") as resp:
            assert await resp.json() == {"reply_hint": ""}

    serve(tmp_path, scenario)


@pytest.fixture
def stt(monkeypatch: pytest.MonkeyPatch, tmp_path: pl.Path) -> FakeStt:
    fake = FakeStt()
    monkeypatch.setitem(providers.STT, "fake", fake)
    vc.connect(tmp_path, "stt", "fake", {})
    return fake


def turn_info(event: str, transcript: str) -> dict[str, str]:
    return {"type": "TurnInfo", "event": event, "transcript": transcript}


def test_the_listen_socket_sends_the_audio_to_the_selected_provider_and_its_turns_to_the_client(tmp_path: pl.Path, stt: FakeStt) -> None:
    async def scenario(client: TestClient) -> None:
        stt.opened = asyncio.Event()
        async with client.ws_connect("/stt/listen") as ws:
            await asyncio.wait_for(stt.opened.wait(), FRAME_TIMEOUT_SECS)
            stream = stt.streams[0]
            await ws.send_bytes(b"pcm")
            await asyncio.wait_for(stream.heard.wait(), FRAME_TIMEOUT_SECS)
            assert stream.audio == [b"pcm"]

            await stream.emit("transcription", "book")
            await stream.emit("transcription", "book a table")
            await stream.emit("committed", "Book a table.")
            assert await next_frame(ws) == turn_info("StartOfTurn", "book")
            assert await next_frame(ws) == turn_info("Update", "book a table")
            assert await next_frame(ws) == turn_info("EndOfTurn", "Book a table.")

            # A commit with no live text before it is a whole turn, and one with no words is none.
            await stream.emit("committed", "")
            await stream.emit("committed", "Thanks.")
            assert await next_frame(ws) == turn_info("StartOfTurn", "Thanks.")
            assert await next_frame(ws) == turn_info("EndOfTurn", "Thanks.")

    serve(tmp_path, scenario)
    assert stt.streams[0].closed is True


def test_the_listen_socket_closes_when_the_provider_connection_goes(tmp_path: pl.Path, stt: FakeStt) -> None:
    async def scenario(client: TestClient) -> None:
        stt.opened = asyncio.Event()
        async with client.ws_connect("/stt/listen") as ws:
            await asyncio.wait_for(stt.opened.wait(), FRAME_TIMEOUT_SECS)
            await stt.streams[0].emit("closed")
            assert (await ws.receive(timeout=FRAME_TIMEOUT_SECS)).type == aiohttp.WSMsgType.CLOSE

    serve(tmp_path, scenario)


def test_the_listen_socket_closes_with_the_reason_when_the_provider_refuses(tmp_path: pl.Path, stt: FakeStt) -> None:
    stt.refuse = "limit"

    async def scenario(client: TestClient) -> None:
        async with client.ws_connect("/stt/listen") as ws:
            closing = await ws.receive(timeout=FRAME_TIMEOUT_SECS)
            assert (closing.data, closing.extra) == (1011, "refused: limit")

    serve(tmp_path, scenario)


def test_the_listen_socket_closes_when_stt_has_no_provider(tmp_path: pl.Path) -> None:
    async def scenario(client: TestClient) -> None:
        async with client.ws_connect("/stt/listen") as ws:
            closing = await ws.receive(timeout=FRAME_TIMEOUT_SECS)
            assert (closing.data, closing.extra) == (1011, "STT not configured")

    serve(tmp_path, scenario)
