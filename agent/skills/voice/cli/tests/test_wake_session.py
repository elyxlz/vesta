"""The wake word gate of a `/voice/session`, driven end to end with a fake detector and fake providers."""

import asyncio
import contextlib
import pathlib as pl
import typing as tp

import aiohttp
import pytest
import voice.config as vc
from aiohttp.test_utils import TestClient
from voice.engine import wake
from voice.settings import JsonValue

from .fakes import FRAME_TIMEOUT_SECS, QUIET_FRAME, WAKE_FRAME, FakeDetector, FakeStt, FakeTts, frames_until, next_frame, voice_service
from .test_session import start

# The quiet frames before the phrase that fill the detector's first window.
QUIET_FRAMES = wake.WINDOW_BYTES // wake.FRAME_BYTES - 1
# The frames the pre-roll keeps: the newest audio that is at least wake.PRE_ROLL_BYTES long.
PRE_ROLL_FRAMES = -(-wake.PRE_ROLL_BYTES // wake.FRAME_BYTES)


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


async def opened(stt: FakeStt) -> None:
    assert stt.opened is not None
    await asyncio.wait_for(stt.opened.wait(), FRAME_TIMEOUT_SECS)
    stt.opened.clear()


def test_no_audio_reaches_speech_to_text_before_the_phrase_and_the_pre_roll_goes_first(
    tmp_path: pl.Path, stt: FakeStt, wake_model: FakeDetector
) -> None:
    wake_on(tmp_path)
    stt.opened = asyncio.Event()

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
            pre_roll = [QUIET_FRAME] * (PRE_ROLL_FRAMES - wake.HIT_FRAMES) + [WAKE_FRAME] * wake.HIT_FRAMES
            assert stt.streams[0].audio == [*pre_roll, b"after"]

    asyncio.run(scenario())


def test_the_phrase_never_reaches_the_agent(tmp_path: pl.Path, stt: FakeStt, wake_model: FakeDetector) -> None:
    wake_on(tmp_path)
    stt.opened = asyncio.Event()

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
    wake_on(tmp_path, wake_word_follow_up_secs=0)
    stt.opened = asyncio.Event()

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
    stt.opened = asyncio.Event()

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, waiting_session(client) as ws:
            await ws.send_json({"type": "speak", "id": "r1", "text": "It will be sunny."})
            # A reply that waits to play is a conversation, so the session listens while it plays.
            assert [frame["type"] for frame in await frames_until(ws, "wake_listening")] == ["play", "wake_listening"]
            await opened(stt)
            await ws.send_json({"type": "playback", "id": "r1", "state": "started"})
            assert await next_frame(ws) == {"type": "state", "value": "agent_speaking"}

            await say_the_phrase(ws)

            assert await frames_until(ws, "state") == [
                {"type": "wake_detected", "score": 1.0},
                {"type": "stop_playback", "id": "r1", "dropped": []},
                {"type": "turn_start"},
                {"type": "state", "value": "user_turn"},
            ]

    asyncio.run(scenario())


def test_turning_the_wake_word_on_closes_the_stream_of_an_open_session(tmp_path: pl.Path, stt: FakeStt, wake_model: FakeDetector) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, client.ws_connect("/voice/session") as ws:
            await ws.send_json(start())
            assert await next_frame(ws) == {"type": "state", "value": "listening"}

            wake_on(tmp_path, wake_word_follow_up_secs=0)

            assert await next_frame(ws) == {"type": "wake_listening", "value": True}
            assert stt.streams[0].closed

    asyncio.run(scenario())


def test_a_phrase_with_no_model_leaves_the_session_listening_with_no_wake_word(
    tmp_path: pl.Path, stt: FakeStt, wake_model: FakeDetector
) -> None:
    wake_on(tmp_path, wake_word_phrase="hey nobody")

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

    asyncio.run(scenario())
