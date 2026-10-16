"""Both STT providers, one contract: each adapter runs against a fake of its provider's socket.

The fake speaks the provider's own wire format, and the test asserts only the events of the
`SttStream` contract, so a new provider is one new row with a fake of its service.
"""

import asyncio
import base64
import contextlib
import dataclasses as dc
import json
import typing as tp

import aiohttp
import pytest
from aiohttp import web
from voice.providers import deepgram, elevenlabs_stt
from voice.providers.base import SttEvent, SttOpenError, SttProvider, SttStream, Usage
from voice.settings import Domain

from .fakes import serving

EVENT_TIMEOUT_SECS = 5
CREDS = {"api_key": "good-key"}
# An outbox entry that makes the fake send a ping in place of a text frame.
PING = "<ping>"


@dc.dataclass
class FakeSocket:
    """What one provider's socket does in a test, and what it saw."""

    # Text frames the server sends: the test puts them, in the provider's wire format.
    outbox: asyncio.Queue[str | None] = dc.field(default_factory=asyncio.Queue)
    pongs: asyncio.Queue[None] = dc.field(default_factory=asyncio.Queue)
    refuse_status: int | None = None
    # When set, the server does not answer the handshake until the test sets it.
    stall: asyncio.Event | None = None
    first_message: dict[str, str] | None = None
    queries: list[dict[str, list[str]]] = dc.field(default_factory=list)
    audio: list[bytes] = dc.field(default_factory=list)
    commit_flags: list[bool] = dc.field(default_factory=list)

    async def handle(self, request: web.Request) -> web.StreamResponse:
        if self.stall is not None:
            await self.stall.wait()
        if self.refuse_status is not None:
            return web.Response(status=self.refuse_status)
        self.queries.append({key: request.query.getall(key) for key in request.query})
        # The fake reads the pongs itself: a pong is how a test knows what the adapter has read.
        ws = web.WebSocketResponse(autoping=False)
        await ws.prepare(request)
        if self.first_message is not None:
            await ws.send_json(self.first_message)
        sender = asyncio.create_task(self._send(ws))
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.PONG:
                self.pongs.put_nowait(None)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                self.audio.append(msg.data)
            elif msg.type == aiohttp.WSMsgType.TEXT:
                chunk = json.loads(msg.data)
                self.audio.append(base64.b64decode(chunk["audio_base_64"]))
                self.commit_flags.append(chunk["commit"])
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender
        return ws

    async def _send(self, ws: web.WebSocketResponse) -> None:
        while True:
            frame = await self.outbox.get()
            if frame is None:
                await ws.close()
                return
            if frame == PING:
                await ws.ping()
            else:
                await ws.send_str(frame)

    async def read_by_the_adapter(self) -> None:
        """Wait until the adapter has read every frame sent so far. It answers a ping only when
        it reads it, and it reads in order, so its pong says that all earlier frames were handled."""
        await self.outbox.put(PING)
        await asyncio.wait_for(self.pongs.get(), EVENT_TIMEOUT_SECS)


@dc.dataclass
class Row:
    """One provider under the contract: its adapter, and how its fake says each thing."""

    name: str
    provider: SttProvider
    module: tp.Any
    base_attr: str
    path: str
    first_message: dict[str, str] | None
    live: tp.Callable[[str], str]
    turn_end: tp.Callable[[str], str]
    # What the fake sends when the adapter commits: the provider's own answer to a commit.
    commit_answer: tp.Callable[[str], str] | None
    bad_key: tp.Callable[[FakeSocket], None]


def _flux(event: str, transcript: str) -> str:
    return json.dumps({"type": "TurnInfo", "event": event, "transcript": transcript})


def _scribe(kind: str, text: str) -> str:
    return json.dumps({"message_type": kind, "text": text})


def _refuse_401(socket: FakeSocket) -> None:
    socket.refuse_status = 401


def _auth_error(socket: FakeSocket) -> None:
    socket.first_message = {"message_type": "auth_error", "error": "invalid key"}


ROWS = [
    Row(
        name="deepgram",
        provider=deepgram.DeepgramStt(),
        module=deepgram,
        base_attr="DEEPGRAM_WS",
        path="/v2/listen",
        first_message=None,
        live=lambda text: _flux("Update", text),
        turn_end=lambda text: _flux("EndOfTurn", text),
        commit_answer=None,
        bad_key=_refuse_401,
    ),
    Row(
        name="elevenlabs",
        provider=elevenlabs_stt.ElevenLabsStt(),
        module=elevenlabs_stt,
        base_attr="ELEVENLABS_WS",
        path="/v1/speech-to-text/realtime",
        first_message={"message_type": "session_started", "session_id": "s1"},
        live=lambda text: _scribe("partial_transcript", text),
        turn_end=lambda text: _scribe("committed_transcript", text),
        commit_answer=lambda text: _scribe("committed_transcript", text),
        bad_key=_auth_error,
    ),
]
BY_NAME = {row.name: row for row in ROWS}


@contextlib.asynccontextmanager
async def provider_socket(row: Row, monkeypatch: pytest.MonkeyPatch, socket: FakeSocket) -> tp.AsyncIterator[None]:
    socket.first_message = socket.first_message or row.first_message
    app = web.Application()
    app.router.add_get(row.path, socket.handle)
    async with serving(app) as client:
        monkeypatch.setattr(row.module, row.base_attr, f"ws://{client.host}:{client.port}")
        yield


async def _next(events: tp.AsyncIterator[SttEvent]) -> SttEvent:
    return await asyncio.wait_for(anext(events), EVENT_TIMEOUT_SECS)


@contextlib.asynccontextmanager
async def open_stream(row: Row, settings: Domain | None = None) -> tp.AsyncIterator[tuple[SttStream, tp.AsyncIterator[SttEvent]]]:
    stream = await row.provider.open(CREDS, settings or {})
    try:
        yield stream, stream.events()
    finally:
        await stream.close()


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_live_text_and_the_end_of_a_turn(row: Row, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        socket = FakeSocket()
        async with provider_socket(row, monkeypatch, socket), open_stream(row) as (_stream, events):
            await socket.outbox.put(row.live("what is"))
            await socket.outbox.put(row.live("what is the weather"))
            await socket.outbox.put(row.turn_end("What is the weather?"))

            assert await _next(events) == {"kind": "transcription", "text": "what is"}
            assert await _next(events) == {"kind": "transcription", "text": "what is the weather"}
            assert await _next(events) == {"kind": "committed", "text": "What is the weather?"}

    asyncio.run(scenario())


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_the_same_live_text_two_times_is_one_event(row: Row, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        socket = FakeSocket()
        async with provider_socket(row, monkeypatch, socket), open_stream(row) as (_stream, events):
            await socket.outbox.put(row.live("hello"))
            await socket.outbox.put(row.live("hello"))
            await socket.outbox.put(row.live("hello there"))

            assert await _next(events) == {"kind": "transcription", "text": "hello"}
            assert await _next(events) == {"kind": "transcription", "text": "hello there"}

    asyncio.run(scenario())


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_mic_audio_reaches_the_provider(row: Row, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        socket = FakeSocket()
        async with provider_socket(row, monkeypatch, socket), open_stream(row) as (stream, events):
            await stream.send(b"\x01\x02\x03\x04")
            await socket.outbox.put(row.live("heard"))
            await _next(events)

            assert socket.audio == [b"\x01\x02\x03\x04"]

    asyncio.run(scenario())


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_commit_ends_the_open_segment_with_its_text(row: Row, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        socket = FakeSocket()
        async with provider_socket(row, monkeypatch, socket), open_stream(row) as (stream, events):
            await socket.outbox.put(row.live("book the table"))
            assert await _next(events) == {"kind": "transcription", "text": "book the table"}

            await stream.commit()
            await stream.send(b"\x00\x00")
            if row.commit_answer is not None:
                await socket.outbox.put(row.commit_answer("book the table"))

            assert await _next(events) == {"kind": "committed", "text": "book the table"}

    asyncio.run(scenario())


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_a_lost_socket_is_a_closed_event_and_it_is_the_last_one(row: Row, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        socket = FakeSocket()
        async with provider_socket(row, monkeypatch, socket), open_stream(row) as (_stream, events):
            await socket.outbox.put(row.live("hello"))
            await socket.outbox.put(None)

            assert await _next(events) == {"kind": "transcription", "text": "hello"}
            assert await _next(events) == {"kind": "closed", "text": ""}
            with pytest.raises(StopAsyncIteration):
                await _next(events)

    asyncio.run(scenario())


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_a_message_the_adapter_cannot_read_ends_the_stream_with_closed(row: Row, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        socket = FakeSocket()
        async with provider_socket(row, monkeypatch, socket), open_stream(row) as (_stream, events):
            await socket.outbox.put("this is not json")

            assert await _next(events) == {"kind": "closed", "text": ""}

    asyncio.run(scenario())


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_a_refused_key_fails_the_open_and_the_check(row: Row, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        socket = FakeSocket()
        row.bad_key(socket)
        async with provider_socket(row, monkeypatch, socket):
            with pytest.raises(SttOpenError) as refused:
                await row.provider.open({"api_key": "bad"}, {})

            assert refused.value.reason == "failed"
            assert await row.provider.validate({"api_key": "bad"}, {}) == (False, "invalid api key")

    asyncio.run(scenario())


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_a_working_key_passes_the_check(row: Row, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        async with provider_socket(row, monkeypatch, FakeSocket()):
            assert await row.provider.validate(CREDS, {}) == (True, None)

    asyncio.run(scenario())


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_a_provider_that_does_not_answer_the_handshake_fails_the_open_at_the_connect_timeout(row: Row, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(row.module, "CONNECT_TIMEOUT_SECS", 0.05)

    async def scenario() -> None:
        stall = asyncio.Event()
        async with provider_socket(row, monkeypatch, FakeSocket(stall=stall, refuse_status=503)):
            with pytest.raises(SttOpenError) as refused:
                await asyncio.wait_for(row.provider.open(CREDS, {}), EVENT_TIMEOUT_SECS)
            stall.set()

            assert refused.value.reason == "failed"

    asyncio.run(scenario())


def test_scribe_at_its_limit_of_sessions_fails_the_open_with_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        socket = FakeSocket(first_message={"message_type": "rate_limited", "error": "too many"})
        async with provider_socket(BY_NAME["elevenlabs"], monkeypatch, socket):
            with pytest.raises(SttOpenError) as refused:
                await BY_NAME["elevenlabs"].provider.open(CREDS, {})

            assert refused.value.reason == "limit"

    asyncio.run(scenario())


def test_flux_at_its_limit_of_sessions_fails_the_open_with_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        async with provider_socket(BY_NAME["deepgram"], monkeypatch, FakeSocket(refuse_status=429)):
            with pytest.raises(SttOpenError) as refused:
                await BY_NAME["deepgram"].provider.open(CREDS, {})

            assert refused.value.reason == "limit"

    asyncio.run(scenario())


def test_scribe_sets_the_commit_flag_on_the_next_audio_chunk_only(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        socket = FakeSocket()
        async with provider_socket(BY_NAME["elevenlabs"], monkeypatch, socket), open_stream(BY_NAME["elevenlabs"]) as (stream, events):
            await stream.send(b"\x00\x00")
            await stream.commit()
            await stream.send(b"\x00\x00")
            await stream.send(b"\x00\x00")
            await socket.outbox.put(_scribe("partial_transcript", "sync"))
            await _next(events)

            assert socket.commit_flags == [False, True, False]

    asyncio.run(scenario())


def test_flux_sends_no_second_committed_for_a_turn_that_commit_already_ended(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        socket = FakeSocket()
        async with provider_socket(BY_NAME["deepgram"], monkeypatch, socket), open_stream(BY_NAME["deepgram"]) as (stream, events):
            await socket.outbox.put(_flux("StartOfTurn", "book"))
            assert await _next(events) == {"kind": "transcription", "text": "book"}
            await stream.commit()
            assert await _next(events) == {"kind": "committed", "text": "book"}

            # Flux still holds the turn open: its later events belong to the committed text.
            await socket.outbox.put(_flux("Update", "book the table"))
            await socket.outbox.put(_flux("EndOfTurn", "Book the table."))
            await socket.outbox.put(_flux("StartOfTurn", "thanks"))

            assert await _next(events) == {"kind": "transcription", "text": "thanks"}

    asyncio.run(scenario())


def test_flux_commit_with_no_open_turn_gives_an_empty_committed_and_drops_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        socket = FakeSocket()
        async with provider_socket(BY_NAME["deepgram"], monkeypatch, socket), open_stream(BY_NAME["deepgram"]) as (stream, events):
            await stream.commit()
            await socket.outbox.put(_flux("StartOfTurn", "hello"))

            assert await _next(events) == {"kind": "committed", "text": ""}
            assert await _next(events) == {"kind": "transcription", "text": "hello"}

    asyncio.run(scenario())


def test_a_flux_commit_while_flux_reports_only_silence_does_not_drop_the_next_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        socket = FakeSocket()
        async with provider_socket(BY_NAME["deepgram"], monkeypatch, socket), open_stream(BY_NAME["deepgram"]) as (stream, events):
            await socket.outbox.put(_flux("Update", ""))
            await socket.read_by_the_adapter()
            await stream.commit()
            await socket.outbox.put(_flux("StartOfTurn", "hello"))
            await socket.outbox.put(_flux("EndOfTurn", "Hello."))

            assert await _next(events) == {"kind": "committed", "text": ""}
            assert await _next(events) == {"kind": "transcription", "text": "hello"}
            assert await _next(events) == {"kind": "committed", "text": "Hello."}

    asyncio.run(scenario())


def test_flux_reads_its_model_its_end_of_turn_tuning_and_the_key_terms_from_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        socket = FakeSocket()
        settings: Domain = {"multi_language": True, "eot_threshold": 0.7, "eot_timeout_ms": 3000, "keyterms": ["Roscioli", "Vesta"]}
        async with provider_socket(BY_NAME["deepgram"], monkeypatch, socket), open_stream(BY_NAME["deepgram"], settings):
            pass

        assert socket.queries[0] == {
            "model": ["flux-general-multi"],
            "encoding": ["linear16"],
            "sample_rate": ["16000"],
            "eot_threshold": ["0.7"],
            "eot_timeout_ms": ["3000"],
            "keyterm": ["Roscioli", "Vesta"],
        }

    asyncio.run(scenario())


def test_scribe_sends_its_two_constants_its_silence_threshold_and_the_key_terms_that_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        socket = FakeSocket()
        settings: Domain = {"vad_silence_threshold_secs": 0.3, "keyterms": ["Roscioli", "a term that is much too long to fit"]}
        async with provider_socket(BY_NAME["elevenlabs"], monkeypatch, socket), open_stream(BY_NAME["elevenlabs"], settings):
            pass

        assert socket.queries[0] == {
            "model_id": ["scribe_v2_realtime"],
            "commit_strategy": ["vad"],
            "audio_format": ["pcm_16000"],
            "vad_silence_threshold_secs": ["0.5"],
            "keyterms": ["Roscioli"],
        }

    asyncio.run(scenario())


def test_the_deepgram_usage_adds_the_hours_of_the_month_and_reads_the_balance(monkeypatch: pytest.MonkeyPatch) -> None:
    async def projects(_request: web.Request) -> web.Response:
        return web.json_response({"projects": [{"project_id": "p1"}]})

    async def breakdown(request: web.Request) -> web.Response:
        assert request.query["endpoint"] == "listen"
        return web.json_response({"results": [{"hours": 3.25}, {"hours": 1.5}, {"requests": 2}]})

    async def balances(_request: web.Request) -> web.Response:
        return web.json_response({"balances": [{"amount": 187.42, "units": "usd"}]})

    async def scenario() -> Usage:
        app = web.Application()
        app.router.add_get("/v1/projects", projects)
        app.router.add_get("/v1/projects/p1/usage/breakdown", breakdown)
        app.router.add_get("/v1/projects/p1/balances", balances)
        async with serving(app) as client:
            monkeypatch.setattr(deepgram, "DEEPGRAM_API", str(client.make_url("")).rstrip("/"))
            return await deepgram.DeepgramStt().usage({"api_key": "dg-key"})

    assert asyncio.run(scenario()) == {"used": {"amount": 4.75, "unit": "hours"}, "left": {"amount": 187.42, "unit": "usd"}}
