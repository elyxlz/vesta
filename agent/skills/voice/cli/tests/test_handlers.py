"""The HTTP routes: status and settings for the app, and the stock app's audio routes."""

import asyncio
import pathlib as pl
import typing as tp

import aiohttp
import pytest
import voice.config as vc
from aiohttp.test_utils import TestClient
from voice import providers
from voice.providers.base import Usage
from voice.settings import JsonValue

from .fakes import FRAME_TIMEOUT_SECS, FakeJudge, FakeStt, FakeTts, next_frame, voice_service


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


def test_speak_mp3_prefers_44100_when_the_provider_makes_it(tmp_path: pl.Path, tts: FakeTts) -> None:
    tts.formats = frozenset({"mp3_22050", "mp3_44100", "pcm_16000"})

    async def scenario(client: TestClient) -> None:
        async with client.post("/tts/speak", json={"text": "Hi"}) as resp:
            assert resp.status == 200
            assert resp.headers["Content-Type"] == "audio/mpeg"

    serve(tmp_path, scenario)
    assert tts.spoken == [("Hi", "v-default", "mp3_44100")]


def test_speak_mp3_falls_back_to_22050_when_the_provider_lacks_44100(tmp_path: pl.Path, tts: FakeTts) -> None:
    tts.formats = frozenset({"mp3_22050"})

    async def scenario(client: TestClient) -> None:
        async with client.post("/tts/speak", json={"text": "Hi"}) as resp:
            assert resp.status == 200

    serve(tmp_path, scenario)
    assert tts.spoken == [("Hi", "v-default", "mp3_22050")]


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


@pytest.mark.parametrize(
    ("made", "expected"),
    [
        (frozenset({"opus_48000", "mp3_44100", "mp3_22050"}), ("opus_48000", "audio/ogg")),
        (frozenset({"mp3_22050"}), ("mp3_22050", "audio/mpeg")),
    ],
)
def test_a_stream_plays_the_first_format_the_client_names_that_the_provider_makes(
    tmp_path: pl.Path, tts: FakeTts, made: frozenset[str], expected: tuple[str, str]
) -> None:
    tts.formats = made

    async def scenario(client: TestClient) -> None:
        async with client.post("/tts/prepare", json={"text": "Later"}) as resp:
            prepared = await resp.json()
        async with client.get(f"/tts/stream/{prepared['id']}", params={"formats": "opus_48000,mp3_44100,mp3_22050"}) as resp:
            assert resp.headers["Content-Type"] == expected[1]

    serve(tmp_path, scenario)
    assert tts.spoken == [("Later", "v-default", expected[0])]


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


def test_the_judge_has_a_status_and_a_switch_like_the_two_other_roles(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(providers.JUDGES, "fake", FakeJudge())

    async def scenario(client: TestClient) -> None:
        async with client.get("/judge/status") as resp:
            assert await resp.json() == {"configured": False, "provider": None, "connected": []}
        vc.connect(tmp_path, "judge", "fake", {})
        async with client.get("/judge/status") as resp:
            assert await resp.json() == {"configured": True, "provider": "fake", "enabled": True, "connected": ["fake"], "settings": []}
        async with client.post("/judge/set-enabled", json={"value": False}) as resp:
            assert await resp.json() == {"ok": True}

    serve(tmp_path, scenario)
    assert vc.is_enabled(vc.load(tmp_path)["judge"]) is False


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


async def usage_of(client: TestClient, role: str) -> dict[str, JsonValue]:
    async with client.get(f"/{role}/usage") as resp:
        assert resp.status == 200
        answer: dict[str, JsonValue] = await resp.json()
        return answer


def test_the_stt_usage_is_the_shape_of_every_provider_with_the_older_app_shape_beside_it(tmp_path: pl.Path, stt: FakeStt) -> None:
    stt.account = {"used": {"amount": 4.75, "unit": "hours"}, "left": {"amount": 187.42, "unit": "usd"}}

    async def scenario(client: TestClient) -> None:
        assert await usage_of(client, "stt") == {
            "used": {"amount": 4.75, "unit": "hours"},
            "left": {"amount": 187.42, "unit": "usd"},
            "usage": {"results": [{"hours": 4.75}]},
            "balance": {"balances": [{"amount": 187.42, "units": "usd"}]},
        }

    serve(tmp_path, scenario)


@pytest.mark.parametrize(
    ("account", "older_app_shape"),
    [
        (
            {"used": {"amount": 1200.0, "unit": "credits"}, "left": {"amount": 8800.0, "unit": "credits"}},
            {"usage": {"character_count": 1200.0, "character_limit": 10000.0}},
        ),
        ({"used": None, "left": {"amount": 8.5, "unit": "usd"}}, {"usage": {"balances": [{"amount": 8.5, "units": "usd"}]}}),
        ({"used": None, "left": None}, {}),
    ],
)
def test_the_tts_usage_is_the_shape_of_every_provider_with_the_older_app_shape_beside_it(
    tmp_path: pl.Path, tts: FakeTts, account: Usage, older_app_shape: dict[str, JsonValue]
) -> None:
    tts.account = account

    async def scenario(client: TestClient) -> None:
        assert await usage_of(client, "tts") == {**account, **older_app_shape}

    serve(tmp_path, scenario)


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


def test_the_listen_socket_closes_and_opens_no_provider_while_stt_is_off(tmp_path: pl.Path, stt: FakeStt) -> None:
    vc.set_enabled(tmp_path, "stt", False)

    async def scenario(client: TestClient) -> None:
        async with client.ws_connect("/stt/listen") as ws:
            closing = await ws.receive(timeout=FRAME_TIMEOUT_SECS)
            assert (closing.data, closing.extra) == (1011, "STT not configured")

    serve(tmp_path, scenario)
    assert stt.streams == []


def test_the_listen_socket_closes_when_stt_has_no_provider(tmp_path: pl.Path) -> None:
    async def scenario(client: TestClient) -> None:
        async with client.ws_connect("/stt/listen") as ws:
            closing = await ws.receive(timeout=FRAME_TIMEOUT_SECS)
            assert (closing.data, closing.extra) == (1011, "STT not configured")

    serve(tmp_path, scenario)
