"""The `/voice/session` socket, driven end to end with a fake provider for each role."""

import asyncio
import contextlib
import pathlib as pl
import typing as tp

import aiohttp
import pytest
import voice.config as vc
from aiohttp.test_utils import TestClient
from voice import providers
from voice.engine import turns
from voice.providers.base import Verdict
from voice.settings import JsonValue

from .fakes import FakeJudge, FakeStream, FakeStt, FakeTts, frames_until, next_frame, voice_service

MIC = {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1}
STOP_VERDICT: Verdict = {"said_to": "agent", "wants_stop": True}
OTHER_VERDICT: Verdict = {"said_to": "other_person", "wants_stop": None}


def start(delivery: str = "url", formats: tuple[str, ...] = ("mp3_44100", "mp3_22050"), **extra: JsonValue) -> dict[str, JsonValue]:
    return {"type": "start_session", "client": "test", "audio": MIC, "playback": {"delivery": delivery, "formats": list(formats)}, **extra}


@pytest.fixture
def stt(monkeypatch: pytest.MonkeyPatch, tmp_path: pl.Path) -> FakeStt:
    fake = FakeStt()
    monkeypatch.setitem(providers.STT, "fake", fake)
    vc.connect(tmp_path, "stt", "fake", {})
    return fake


@pytest.fixture
def tts(monkeypatch: pytest.MonkeyPatch, tmp_path: pl.Path) -> FakeTts:
    fake = FakeTts()
    monkeypatch.setitem(providers.TTS, "fake", fake)
    vc.connect(tmp_path, "tts", "fake", {})
    return fake


@pytest.fixture
def judge(monkeypatch: pytest.MonkeyPatch, tmp_path: pl.Path) -> FakeJudge:
    fake = FakeJudge()
    monkeypatch.setitem(providers.JUDGES, "fake", fake)
    vc.connect(tmp_path, "judge", "fake", {})
    vc.set_enabled(tmp_path, "judge", True)
    return fake


@contextlib.asynccontextmanager
async def session(
    client: TestClient, stt: FakeStt, first: dict[str, JsonValue] | None = None
) -> tp.AsyncIterator[tuple[aiohttp.ClientWebSocketResponse, FakeStream]]:
    """An open session, after its first `state` frame."""
    async with client.ws_connect("/voice/session") as ws:
        await ws.send_json(first if first is not None else start())
        assert await next_frame(ws) == {"type": "state", "value": "listening"}
        yield ws, stt.streams[-1]


async def speak_and_start(ws: aiohttp.ClientWebSocketResponse, play_id: str = "r1", text: str = "It will be sunny.") -> dict[str, JsonValue]:
    """Speak one reply and report that the speaker started it. Returns the `play` frame."""
    await ws.send_json({"type": "speak", "id": play_id, "text": text})
    play = await next_frame(ws)
    await ws.send_json({"type": "playback", "id": play_id, "state": "started"})
    assert await next_frame(ws) == {"type": "state", "value": "agent_speaking"}
    return play


def test_mic_audio_reaches_the_stt_provider(tmp_path: pl.Path, stt: FakeStt) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, stream):
            await ws.send_bytes(b"\x01\x02")
            await ws.send_json({"type": "end_turn"})
            await stream.emit("committed", "")
            await ws.send_json({"type": "end_session"})
            await frames_until(ws, "ended")
            assert stream.audio == [b"\x01\x02"]

    asyncio.run(scenario())


def test_a_turn_goes_from_live_text_to_turn_end(tmp_path: pl.Path, stt: FakeStt) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, stream):
            await stream.emit("transcription", "what is")
            await stream.emit("transcription", "what is the weather")
            await stream.emit("committed", "What is the weather?")

            assert await frames_until(ws, "state") == [
                {"type": "transcript", "text": "what is"},
                {"type": "turn_start"},
                {"type": "state", "value": "user_turn"},
            ]
            assert await frames_until(ws, "state") == [
                {"type": "transcript", "text": "what is the weather"},
                {"type": "turn_end", "text": "What is the weather?"},
                {"type": "state", "value": "listening"},
            ]

    asyncio.run(scenario())


def test_end_turn_commits_the_open_segment(tmp_path: pl.Path, stt: FakeStt) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, stream):
            await stream.emit("transcription", "book it")
            await frames_until(ws, "state")
            await ws.send_json({"type": "end_turn"})
            await ws.send_json({"type": "end_session"})
            await frames_until(ws, "ended")
            assert stream.commits == 1

    asyncio.run(scenario())


def test_url_delivery_gives_a_url_that_serves_the_audio_of_the_play(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, _stream):
            await ws.send_json({"type": "speak", "id": "r1", "text": "Hi"})
            play = await next_frame(ws)

            assert {key: play[key] for key in ("type", "id", "format")} == {"type": "play", "id": "r1", "format": "mp3_22050"}
            assert str(play["url"]).startswith("/voice/play/")
            async with client.get(str(play["url"])) as audio:
                assert audio.status == 200
                assert audio.headers["Content-Type"] == "audio/mpeg"
                assert await audio.read() == b"auHidioHi"
            assert tts.spoken == [("Hi", "v-default", "mp3_22050")]

    asyncio.run(scenario())


def test_the_agent_is_speaking_from_the_started_report_to_the_finished_report(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, _stream):
            await speak_and_start(ws)
            await ws.send_json({"type": "playback", "id": "r1", "state": "finished"})

            assert await next_frame(ws) == {"type": "state", "value": "listening"}

    asyncio.run(scenario())


def test_bytes_delivery_sends_all_the_bytes_of_one_play_before_the_next_play(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt, start("bytes")) as (ws, _stream):
            await ws.send_json({"type": "speak", "id": "r1", "text": "One"})
            await ws.send_json({"type": "speak", "id": "r2", "text": "Two"})

            seen: list[JsonValue | bytes] = []
            while len([item for item in seen if isinstance(item, dict) and item["type"] == "play_done"]) < 2:
                msg = await ws.receive(timeout=5)
                seen.append(msg.data if msg.type == aiohttp.WSMsgType.BINARY else msg.json())

            assert seen == [
                {"type": "play", "id": "r1", "format": "mp3_22050"},
                b"auOne",
                b"dioOne",
                {"type": "play_done", "id": "r1"},
                {"type": "play", "id": "r2", "format": "mp3_22050"},
                b"auTwo",
                b"dioTwo",
                {"type": "play_done", "id": "r2"},
            ]

    asyncio.run(scenario())


def test_with_no_judge_a_short_backchannel_pauses_and_then_resumes_the_reply(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, stream):
            await speak_and_start(ws)
            await stream.emit("transcription", "mhm")
            assert await frames_until(ws, "state") == [
                {"type": "transcript", "text": "mhm"},
                {"type": "pause_playback"},
                {"type": "state", "value": "agent_paused"},
            ]

            await stream.emit("committed", "Mhm.")
            assert await frames_until(ws, "state") == [
                {"type": "resume_playback"},
                {"type": "ignored", "text": "Mhm.", "kind": "backchannel"},
                {"type": "state", "value": "agent_speaking"},
            ]

    asyncio.run(scenario())


def test_with_no_judge_speech_that_continues_past_the_hold_time_stops_the_reply(
    tmp_path: pl.Path, stt: FakeStt, tts: FakeTts, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(turns, "HOLD_WAIT_MS", 30)

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, stream):
            await speak_and_start(ws, "r1")
            await ws.send_json({"type": "speak", "id": "r2", "text": "And tomorrow rain."})
            await next_frame(ws)
            await stream.emit("transcription", "wait I meant")

            assert await frames_until(ws, "state") == [
                {"type": "transcript", "text": "wait I meant"},
                {"type": "pause_playback"},
                {"type": "state", "value": "agent_paused"},
            ]
            assert await frames_until(ws, "state") == [
                {"type": "stop_playback", "id": "r1", "dropped": ["r2"]},
                {"type": "turn_start"},
                {"type": "state", "value": "user_turn"},
            ]

    asyncio.run(scenario())


def test_the_judge_decides_a_barge_in_and_sees_what_the_agent_is_saying(
    tmp_path: pl.Path, stt: FakeStt, tts: FakeTts, judge: FakeJudge
) -> None:
    judge.verdicts = {"stop": STOP_VERDICT, "Stop.": STOP_VERDICT}

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, stream):
            await speak_and_start(ws, "r1", "It will be sunny.")
            await stream.emit("transcription", "stop")

            assert await frames_until(ws, "state") == [
                {"type": "transcript", "text": "stop"},
                {"type": "pause_playback"},
                {"type": "state", "value": "agent_paused"},
            ]
            assert await frames_until(ws, "state") == [
                {"type": "stop_playback", "id": "r1", "dropped": []},
                {"type": "turn_start"},
                {"type": "state", "value": "user_turn"},
            ]
            assert judge.asked[0] == {"agent_name": "agent", "recent": [], "agent_saying": "It will be sunny.", "user_saying": "stop"}

            await stream.emit("committed", "Stop.")
            assert await frames_until(ws, "state") == [{"type": "turn_end", "text": "Stop."}, {"type": "state", "value": "listening"}]
            # The cut reply and the delivered turn are the lines the judge sees next.
            await stream.emit("transcription", "thanks")
            await frames_until(ws, "transcript")
            await ws.send_json({"type": "end_session"})
            await frames_until(ws, "ended")
            assert judge.asked[-1]["recent"] == [{"by": "agent", "text": "It will be sunny."}, {"by": "user", "text": "Stop."}]

    asyncio.run(scenario())


def test_the_judge_keeps_words_for_another_person_out_of_the_conversation(tmp_path: pl.Path, stt: FakeStt, judge: FakeJudge) -> None:
    judge.verdicts = {"honey did you": OTHER_VERDICT, "Honey, did you take the trash out?": OTHER_VERDICT}

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, stream):
            await stream.emit("transcription", "honey did you")
            await stream.emit("committed", "Honey, did you take the trash out?")

            assert await frames_until(ws, "ignored") == [
                {"type": "transcript", "text": "honey did you"},
                {"type": "ignored", "text": "Honey, did you take the trash out?", "kind": "other_person"},
            ]

    asyncio.run(scenario())


def test_a_session_with_the_judge_off_asks_the_judge_nothing(tmp_path: pl.Path, stt: FakeStt, judge: FakeJudge) -> None:
    vc.set_enabled(tmp_path, "judge", False)

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, stream):
            await stream.emit("transcription", "hello")
            await stream.emit("committed", "Hello.")
            await frames_until(ws, "turn_end")

    asyncio.run(scenario())
    assert judge.asked == []


def test_a_reply_that_arrives_during_the_users_turn_waits_for_the_end_of_the_turn(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts) -> None:
    async def scenario() -> None:
        tts.heard = asyncio.Event()
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, stream):
            await stream.emit("transcription", "and also")
            await frames_until(ws, "state")
            await ws.send_json({"type": "speak", "id": "r1", "text": "Done."})
            await asyncio.wait_for(tts.heard.wait(), timeout=5)
            await stream.emit("committed", "And also the dentist.")

            after = await frames_until(ws, "state")
            assert [frame["type"] for frame in after] == ["turn_end", "play", "state"]
            assert after[1]["id"] == "r1"

    asyncio.run(scenario())


def test_a_session_that_cannot_do_barge_in_never_pauses_and_still_has_turns(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt, start(barge_in=False)) as (ws, stream):
            await speak_and_start(ws)
            await stream.emit("transcription", "note to self")
            await stream.emit("committed", "Note to self.")

            assert await frames_until(ws, "turn_end") == [
                {"type": "transcript", "text": "note to self"},
                {"type": "turn_start"},
                {"type": "state", "value": "user_turn"},
                {"type": "turn_end", "text": "Note to self."},
            ]

    asyncio.run(scenario())


def test_the_stored_behavior_takes_barge_in_away_from_every_session(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts) -> None:
    vc.set_setting(tmp_path, "behavior", "barge_in", False)

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt, start(barge_in=True)) as (ws, stream):
            await speak_and_start(ws)
            await stream.emit("transcription", "hello")

            assert await frames_until(ws, "turn_start") == [{"type": "transcript", "text": "hello"}, {"type": "turn_start"}]

    asyncio.run(scenario())


def test_a_change_of_a_behavior_during_a_session_does_not_change_that_session(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, stream):
            vc.set_setting(tmp_path, "behavior", "barge_in", False)
            await speak_and_start(ws)
            await stream.emit("transcription", "mhm")

            assert await frames_until(ws, "pause_playback") == [{"type": "transcript", "text": "mhm"}, {"type": "pause_playback"}]

    asyncio.run(scenario())


def test_the_user_stops_the_reply_on_the_device(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, _stream):
            await speak_and_start(ws, "r1")
            await ws.send_json({"type": "playback", "id": "r1", "state": "stopped_by_user"})

            assert await frames_until(ws, "state") == [
                {"type": "stop_playback", "id": "r1", "dropped": []},
                {"type": "state", "value": "listening"},
            ]

    asyncio.run(scenario())


def test_in_bytes_delivery_a_stop_ends_the_bytes_of_the_play(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts) -> None:
    async def scenario() -> None:
        tts.gate = asyncio.Event()
        async with voice_service(tmp_path) as client, session(client, stt, start("bytes")) as (ws, _stream):
            await ws.send_json({"type": "speak", "id": "r1", "text": "Long"})
            assert await next_frame(ws) == {"type": "play", "id": "r1", "format": "mp3_22050"}
            assert await ws.receive_bytes(timeout=5) == b"auLong"
            await ws.send_json({"type": "playback", "id": "r1", "state": "started"})
            assert await next_frame(ws) == {"type": "state", "value": "agent_speaking"}

            await ws.send_json({"type": "playback", "id": "r1", "state": "stopped_by_user"})
            assert await next_frame(ws) == {"type": "stop_playback", "id": "r1", "dropped": []}
            tts.gate.set()
            # The rest of the play never follows the stop: the next frames are text frames only.
            assert await next_frame(ws) == {"type": "state", "value": "listening"}
            await ws.send_json({"type": "end_session"})
            assert await next_frame(ws) == {"type": "ended", "reason": "client_ended"}

    asyncio.run(scenario())


def test_speak_with_tts_off_gives_an_error_and_no_play(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts) -> None:
    vc.set_enabled(tmp_path, "tts", False)

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, _stream):
            await ws.send_json({"type": "speak", "id": "r1", "text": "Hi"})
            await ws.send_json({"type": "end_session"})

            frames = await frames_until(ws, "ended")
            assert [frame["type"] for frame in frames] == ["error", "ended"]

    asyncio.run(scenario())
    assert tts.spoken == []


def test_a_failed_synthesis_gives_an_error_and_its_url_answers_502(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts) -> None:
    tts.fail = True

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, _stream):
            await ws.send_json({"type": "speak", "id": "r1", "text": "Hi"})
            frames = await frames_until(ws, "error")
            play = next(frame for frame in frames if frame["type"] == "play")

            assert frames[-1] == {"type": "error", "message": "the fake refused the synthesis"}
            async with client.get(str(play["url"])) as audio:
                assert audio.status == 502

    asyncio.run(scenario())


def test_a_frame_before_start_session_gets_an_error_and_the_session_can_still_start(tmp_path: pl.Path, stt: FakeStt) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, client.ws_connect("/voice/session") as ws:
            await ws.send_json({"type": "speak", "id": "r1", "text": "Hi"})
            await ws.send_bytes(b"\x00\x00")
            await ws.send_json({"type": "start_session", "client": "test"})
            await ws.send_json(start())

            frames = await frames_until(ws, "state")
            assert [frame["type"] for frame in frames] == ["error", "error", "error", "state"]

    asyncio.run(scenario())


def test_a_second_start_session_gets_an_error_and_changes_nothing(tmp_path: pl.Path, stt: FakeStt) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, _stream):
            await ws.send_json(start())
            await ws.send_json({"type": "made_up_frame"})
            await ws.send_json({"type": "end_session"})

            assert [frame["type"] for frame in await frames_until(ws, "ended")] == ["error", "ended"]
            assert len(stt.streams) == 1

    asyncio.run(scenario())


ENDED_ROWS = [
    ("the stt role has no provider", None, start(), "not_configured"),
    (
        "the mic format is not supported",
        "ok",
        {**start(), "audio": {"encoding": "opus", "sample_rate": 48000, "channels": 1}},
        "unsupported_format",
    ),
    ("the tts provider can make none of the formats", "ok", start(formats=("opus_48000", "flac")), "unsupported_format"),
    ("the stt provider refuses the connection", "failed", start(), "stt_failed"),
    ("the stt provider is at its limit of sessions", "limit", start(), "stt_limit"),
]


@pytest.mark.parametrize(("name", "stt_setup", "first", "reason"), ENDED_ROWS, ids=[row[0] for row in ENDED_ROWS])
def test_a_session_that_cannot_start_ends_with_its_reason(
    tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch, name: str, stt_setup: str | None, first: dict[str, JsonValue], reason: str
) -> None:
    monkeypatch.setitem(providers.TTS, "fake", FakeTts())
    vc.connect(tmp_path, "tts", "fake", {})
    if stt_setup is not None:
        refuse: tp.Literal["failed", "limit"] | None = "failed" if stt_setup == "failed" else "limit" if stt_setup == "limit" else None
        monkeypatch.setitem(providers.STT, "fake", FakeStt(refuse=refuse))
        vc.connect(tmp_path, "stt", "fake", {})

    async def scenario() -> None:
        async with voice_service(tmp_path) as client, client.ws_connect("/voice/session") as ws:
            await ws.send_json(first)
            assert await next_frame(ws) == {"type": "ended", "reason": reason}

    asyncio.run(scenario())


def test_a_session_with_no_tts_provider_opens_whatever_formats_it_lists(tmp_path: pl.Path, stt: FakeStt) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt, start(formats=("flac",))) as (ws, _stream):
            await ws.send_json({"type": "end_session"})
            assert await next_frame(ws) == {"type": "ended", "reason": "client_ended"}

    asyncio.run(scenario())


def test_a_lost_stt_connection_ends_the_session_and_closes_the_stream(tmp_path: pl.Path, stt: FakeStt) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, stream):
            await stream.emit("closed")

            assert await next_frame(ws) == {"type": "ended", "reason": "stt_failed"}
            await ws.receive(timeout=5)
            assert stream.closed is True

    asyncio.run(scenario())


def test_a_client_that_goes_away_closes_the_stt_connection(tmp_path: pl.Path, stt: FakeStt) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client:
            async with session(client, stt) as (_ws, stream):
                pass
            await asyncio.wait_for(_closed(stream), timeout=5)

    async def _closed(stream: FakeStream) -> None:
        async for event in stream.events():
            if event["kind"] == "closed":
                return

    asyncio.run(scenario())


def test_a_failure_inside_the_engine_tells_the_client_before_the_socket_closes(tmp_path: pl.Path, stt: FakeStt) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, stream):
            stream.broken = True
            await ws.send_bytes(b"\x00\x00")

            failed = await next_frame(ws)
            assert failed["type"] == "error"
            assert "the engine failed" in str(failed["message"])
            assert (await ws.receive(timeout=5)).type == aiohttp.WSMsgType.CLOSE
            assert stream.closed is True

    asyncio.run(scenario())


def test_two_sessions_speak_the_same_id_and_each_gets_its_own_audio(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (one, _s1), session(client, stt) as (two, _s2):
            await one.send_json({"type": "speak", "id": "r1", "text": "Hi"})
            await two.send_json({"type": "speak", "id": "r1", "text": "Hi"})
            first, second = await next_frame(one), await next_frame(two)

            assert first["url"] != second["url"]
            for play in (first, second):
                async with client.get(str(play["url"])) as audio:
                    assert await audio.read() == b"auHidioHi"
            assert len(tts.spoken) == 2

    asyncio.run(scenario())


def test_a_stop_in_one_session_stops_nothing_in_the_other(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (one, _s1), session(client, stt) as (two, _s2):
            await speak_and_start(one, "r1")
            await speak_and_start(two, "r1")
            await one.send_json({"type": "playback", "id": "r1", "state": "stopped_by_user"})
            await frames_until(one, "state")

            await two.send_json({"type": "playback", "id": "r1", "state": "finished"})
            assert await next_frame(two) == {"type": "state", "value": "listening"}

    asyncio.run(scenario())


def test_a_lost_stt_connection_ends_one_session_and_the_other_continues(tmp_path: pl.Path, stt: FakeStt) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (one, first), session(client, stt) as (two, second):
            await first.emit("closed")
            assert await next_frame(one) == {"type": "ended", "reason": "stt_failed"}

            await second.emit("transcription", "still here")
            assert await next_frame(two) == {"type": "transcript", "text": "still here"}

    asyncio.run(scenario())


@pytest.mark.parametrize("last_report", ["finished", "failed"])
def test_the_url_of_a_play_answers_404_after_the_speaker_is_done_with_it(
    tmp_path: pl.Path, stt: FakeStt, tts: FakeTts, last_report: str
) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, _stream):
            play = await speak_and_start(ws)
            async with client.get(str(play["url"])) as audio:
                assert audio.status == 200

            await ws.send_json({"type": "playback", "id": "r1", "state": last_report})
            assert await next_frame(ws) == {"type": "state", "value": "listening"}

            async with client.get(str(play["url"])) as audio:
                assert audio.status == 404

    asyncio.run(scenario())


def test_the_url_of_a_play_answers_404_after_its_session_ends(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client:
            async with session(client, stt) as (ws, _stream):
                await ws.send_json({"type": "speak", "id": "r1", "text": "Hi"})
                play = await next_frame(ws)
                await ws.send_json({"type": "end_session"})
                await frames_until(ws, "ended")
                await ws.receive(timeout=5)
            async with client.get(str(play["url"])) as audio:
                assert audio.status == 404

    asyncio.run(scenario())


def test_live_text_that_ends_with_no_other_frame_tells_the_client_that_it_is_over(tmp_path: pl.Path, stt: FakeStt, tts: FakeTts) -> None:
    async def scenario() -> None:
        async with voice_service(tmp_path) as client, session(client, stt) as (ws, stream):
            await speak_and_start(ws)
            await stream.emit("transcription", "uh")
            await frames_until(ws, "state")

            await stream.emit("committed", "")
            assert await frames_until(ws, "transcript") == [
                {"type": "resume_playback"},
                {"type": "state", "value": "agent_speaking"},
                {"type": "transcript", "text": ""},
            ]

    asyncio.run(scenario())
