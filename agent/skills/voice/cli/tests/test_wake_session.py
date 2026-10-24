"""The wake word gate of a `/voice/session`, driven end to end with a fake detector and fake providers."""

import asyncio
import contextlib
import pathlib as pl
import typing as tp

import aiohttp
import pytest
import voice.config as vc
from aiohttp.test_utils import TestClient
from voice.engine import behavior, wake
from voice.engine import session as engine_session
from voice.settings import Domain, JsonValue

from .fakes import (
    FRAME_TIMEOUT_SECS,
    QUIET_FRAME,
    WAKE_FRAME,
    FakeDetector,
    FakeStt,
    FakeTts,
    frames_until,
    next_frame,
    opened,
    voice_service,
)
from .test_session import session, start

# The quiet frames before the phrase that fill the detector's first window.
QUIET_FRAMES = wake.WINDOW_BYTES // wake.FRAME_BYTES - 1


def wake_on(data_dir: pl.Path, **settings: bool | int | float | str) -> None:
    vc.mutate(data_dir, lambda cfg: {**cfg, "behavior": {"wake_word": True, **settings}})


@contextlib.asynccontextmanager
async def waiting_session(client: TestClient) -> tp.AsyncIterator[aiohttp.ClientWebSocketResponse]:
    """An open session that waits for the wake word."""
    async with client.ws_connect("/voice/session") as ws:
        await ws.send_json(start())
        assert await frames_until(ws, "wake_listening") == [{"type": "state", "value": "listening"}, {"type": "wake_listening", "value": True}]
        yield ws


async def say_the_phrase(ws: aiohttp.ClientWebSocketResponse) -> None:
    for _ in range(QUIET_FRAMES):
        await ws.send_bytes(QUIET_FRAME)
    for _ in range(wake.HIT_FRAMES):
        await ws.send_bytes(WAKE_FRAME)


async def read_up_to_here(ws: aiohttp.ClientWebSocketResponse) -> None:
    """The session reads client frames in order, so its answer to a bad frame shows that it read
    every frame sent before it."""
    await ws.send_str("not json")
    assert await next_frame(ws) == {"type": "error", "message": "the frame is not JSON"}


def test_no_audio_reaches_speech_to_text_before_the_phrase_and_the_pre_roll_goes_first(
    tmp_path: pl.Path, stt: FakeStt, wake_model: FakeDetector
) -> None:
    wake_on(tmp_path)

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, waiting_session(client) as ws:
            await say_the_phrase(ws)

            assert await frames_until(ws, "wake_listening") == [
                {"type": "wake_detected", "score": 1.0},
                {"type": "wake_listening", "value": False},
            ]
            await opened(stt)
            await ws.send_bytes(b"after")
            # The pre-roll goes out in one step, so the first audio means all of it is there.
            await asyncio.wait_for(stt.streams[0].heard.wait(), FRAME_TIMEOUT_SECS)
            await read_up_to_here(ws)

            assert len(stt.streams) == 1
            said = QUIET_FRAME * QUIET_FRAMES + WAKE_FRAME * wake.HIT_FRAMES
            assert stt.streams[0].audio == [said[-wake.PRE_ROLL_BYTES :], b"after"]

    asyncio.run(scenario())


def test_the_phrase_never_reaches_the_agent(tmp_path: pl.Path, stt: FakeStt, wake_model: FakeDetector) -> None:
    wake_on(tmp_path)

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, waiting_session(client) as ws:
            await say_the_phrase(ws)
            await frames_until(ws, "wake_listening")
            await opened(stt)
            stream = stt.streams[0]
            await stream.emit("transcription", "hey")
            await stream.emit("transcription", "hey aria what time")
            await stream.emit("committed", "Hey Aria, what time is it?")

            assert await frames_until(ws, "turn_end") == [
                {"type": "transcript", "text": "what time"},
                {"type": "turn_start"},
                {"type": "state", "value": "user_turn"},
                {"type": "transcript", "text": ""},
                {"type": "turn_end", "text": "what time is it?"},
            ]

    asyncio.run(scenario())


def test_after_the_turn_and_the_follow_up_window_the_session_waits_again(
    tmp_path: pl.Path, stt: FakeStt, wake_model: FakeDetector, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wake, "HEARD_SECS", 0.3)
    monkeypatch.setattr(behavior, "MIN_FOLLOW_UP_SECS", 0)
    wake_on(tmp_path, wake_word_follow_up_secs=0)

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, waiting_session(client) as ws:
            await say_the_phrase(ws)
            await frames_until(ws, "wake_listening")
            await opened(stt)
            await stt.streams[0].emit("transcription", "hey aria book it")
            await stt.streams[0].emit("committed", "Hey Aria, book it.")
            await frames_until(ws, "turn_end")

            assert await frames_until(ws, "wake_listening") == [
                {"type": "state", "value": "listening"},
                {"type": "wake_listening", "value": True},
            ]
            assert stt.streams[0].closed

            await say_the_phrase(ws)
            assert await frames_until(ws, "wake_listening") == [
                {"type": "wake_detected", "score": 1.0},
                {"type": "wake_listening", "value": False},
            ]
            await opened(stt)
            assert len(stt.streams) == 2

    asyncio.run(scenario())


def test_the_phrase_over_a_reply_stops_it_at_once(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts, wake_model: FakeDetector) -> None:
    wake_on(tmp_path)

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, waiting_session(client) as ws:
            await ws.send_json({"type": "speak", "id": "r1", "text": "It will be sunny."})
            # While a reply plays or waits to play, only the phrase gets through: no stream opens.
            assert (await next_frame(ws))["type"] == "play"
            await ws.send_json({"type": "playback", "id": "r1", "state": "started"})
            assert await next_frame(ws) == {"type": "state", "value": "agent_speaking"}
            assert stt.streams == []

            await say_the_phrase(ws)

            assert await frames_until(ws, "state") == [
                {"type": "wake_detected", "score": 1.0},
                {"type": "stop_playback", "id": "r1", "dropped": []},
                {"type": "state", "value": "listening"},
            ]

    asyncio.run(scenario())


def test_turning_the_wake_word_on_closes_the_stream_of_an_open_session(
    tmp_path: pl.Path, stt: FakeStt, wake_model: FakeDetector, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(behavior, "MIN_FOLLOW_UP_SECS", 0)

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, _stream):
            wake_on(tmp_path, wake_word_follow_up_secs=0)

            assert await next_frame(ws) == {"type": "wake_listening", "value": True}
            assert stt.streams[0].closed

    asyncio.run(scenario())


def test_a_phrase_with_no_model_leaves_the_session_listening_with_no_wake_word(
    tmp_path: pl.Path, stt: FakeStt, wake_model: FakeDetector, monkeypatch: pytest.MonkeyPatch
) -> None:
    wake_on(tmp_path, wake_word_phrase="hey nobody")
    applied = asyncio.Event()
    apply_behavior = engine_session._apply_behavior

    async def apply_and_tell(open_session: engine_session.Session, stored: Domain) -> None:
        await apply_behavior(open_session, stored)
        applied.set()

    monkeypatch.setattr(engine_session, "_apply_behavior", apply_and_tell)

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, client.ws_connect("/voice/session") as ws:
            await ws.send_json(start())
            error = await next_frame(ws)
            assert await next_frame(ws) == {"type": "state", "value": "listening"}
            await ws.send_bytes(b"hello")
            await read_up_to_here(ws)

            message: JsonValue = error["message"]
            assert isinstance(message, str)
            assert message.startswith("the wake word is on but cannot run, so this session listens without it: no wake word model at")
            assert stt.streams[0].audio == [b"hello"]
            assert wake_model.windows == 0

            # A change of an other behavior does not tell the same failure again: the next error
            # is the one of the next phrase.
            applied.clear()
            vc.set_setting(tmp_path, "behavior", "wake_word_threshold", 0.7)
            await asyncio.wait_for(applied.wait(), FRAME_TIMEOUT_SECS)
            vc.set_setting(tmp_path, "behavior", "wake_word_phrase", "hey other")
            other: JsonValue = (await next_frame(ws))["message"]
            assert isinstance(other, str)
            assert other.endswith("hey_other.onnx")

    asyncio.run(scenario())


def test_a_session_that_states_no_wake_word_listens_with_none(tmp_path: pl.Path, stt: FakeStt, wake_model: FakeDetector) -> None:
    wake_on(tmp_path)

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt, start(wake_word=False)) as (ws, _stream):
            await ws.send_bytes(b"hello")
            await read_up_to_here(ws)

            assert stt.streams[0].audio == [b"hello"]
            assert wake_model.windows == 0

    asyncio.run(scenario())


def test_a_refused_stream_leaves_the_session_open_and_the_gate_tries_again(
    tmp_path: pl.Path, stt: FakeStt, wake_model: FakeDetector, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wake, "RETRY_SECS", 0.3)
    wake_on(tmp_path)
    stt.refuse = "limit"

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, waiting_session(client) as ws:
            await say_the_phrase(ws)

            assert await frames_until(ws, "error") == [
                {"type": "wake_detected", "score": 1.0},
                {"type": "wake_listening", "value": False},
                {"type": "error", "message": "speech to text refused a stream (limit); the session tries again in 0.3 s"},
            ]
            stt.refuse = None
            await opened(stt)
            await ws.send_bytes(b"after")
            await asyncio.wait_for(stt.streams[0].heard.wait(), FRAME_TIMEOUT_SECS)

            assert stt.streams[0].audio == [b"after"]

    asyncio.run(scenario())
