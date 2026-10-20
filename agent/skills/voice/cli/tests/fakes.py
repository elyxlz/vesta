"""Fakes for the voice tests: a provider of each role, and a provider's server on a local port."""

import asyncio
import contextlib
import dataclasses as dc
import pathlib as pl
import typing as tp

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from voice import server
from voice.engine import wake
from voice.providers.base import Question, SttEvent, SttOpenError, TtsError, Usage, Validation, Verdict, no_usage
from voice.settings import Domain, JsonValue, SettingDef, SettingOption

FRAME_TIMEOUT_SECS = 5


class FakeStream:
    """An STT stream the test drives: `emit` is what the provider heard."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[SttEvent] = asyncio.Queue()
        self.audio: list[bytes] = []
        self.commits = 0
        self.closed = False
        # Set when audio arrives, so a test can wait for a frame that gets no answer.
        self.heard = asyncio.Event()
        # When true, `send` raises an error that is not part of the contract: an adapter bug.
        self.broken = False

    async def send(self, pcm: bytes) -> None:
        if self.broken:
            raise RuntimeError("the adapter broke")
        self.audio.append(pcm)
        self.heard.set()

    async def commit(self) -> None:
        self.commits += 1

    async def close(self) -> None:
        self.closed = True
        await self.queue.put({"kind": "closed", "text": ""})

    async def events(self) -> tp.AsyncIterator[SttEvent]:
        while True:
            event = await self.queue.get()
            yield event
            if event["kind"] == "closed":
                return

    async def emit(self, kind: tp.Literal["transcription", "committed", "closed"], text: str = "") -> None:
        await self.queue.put({"kind": kind, "text": text})


@dc.dataclass
class FakeStt:
    needs_key: bool = False
    refuse: tp.Literal["failed", "limit"] | None = None
    valid: bool = True
    account: Usage = dc.field(default_factory=no_usage)
    streams: list[FakeStream] = dc.field(default_factory=list)
    # When set, an open sets it: the route opened a stream and sends no frame to say so.
    opened: asyncio.Event | None = None
    opened_with: list[tuple[dict[str, str], Domain]] = dc.field(default_factory=list)

    async def open(self, creds: dict[str, str], settings: Domain) -> FakeStream:
        if self.refuse is not None:
            raise SttOpenError(self.refuse, f"refused: {self.refuse}")
        self.opened_with.append((creds, settings))
        self.streams.append(FakeStream())
        if self.opened is not None:
            self.opened.set()
        return self.streams[-1]

    async def validate(self, creds: dict[str, str], settings: Domain) -> Validation:
        return (True, None) if self.valid else (False, "the fake says no")

    async def transcribe_file(self, audio_path: pl.Path, creds: dict[str, str], language: str | None) -> str:
        return ""

    async def usage(self, creds: dict[str, str]) -> Usage:
        return self.account

    def settings_schema(self) -> list[SettingDef]:
        return [{"key": "address", "type": "text", "default": "http://127.0.0.1:9000"}]


@dc.dataclass
class FakeTts:
    needs_key: bool = False
    voice_setting: str = "fake_voice"
    formats: frozenset[str] = frozenset({"mp3_22050", "pcm_16000"})
    reply_hint: str = ""
    account: Usage = dc.field(default_factory=no_usage)
    chunks: tuple[bytes, ...] = (b"au", b"dio")
    fail: bool = False
    valid: bool = True
    # When set, synthesis sends one chunk and then waits for the test to release the rest.
    gate: asyncio.Event | None = None
    # When set, a synthesis that starts sets it: the engine handled a `speak` that sends no frame.
    heard: asyncio.Event | None = None
    spoken: list[tuple[str, str, str]] = dc.field(default_factory=list)

    async def synthesize(
        self, text: str, voice: str, audio_format: str, creds: dict[str, str], settings: Domain, http: aiohttp.ClientSession
    ) -> tp.AsyncIterator[bytes]:
        self.spoken.append((text, voice, audio_format))
        if self.heard is not None:
            self.heard.set()
        if self.fail:
            raise TtsError("the fake refused the synthesis")
        for index, chunk in enumerate(self.chunks):
            if index == 1 and self.gate is not None:
                await self.gate.wait()
            yield chunk + text.encode()

    async def usage(self, creds: dict[str, str]) -> Usage:
        return self.account

    async def validate(self, creds: dict[str, str], settings: Domain) -> Validation:
        return (True, None) if self.valid else (False, "the fake says no")

    def settings_schema(self) -> list[SettingDef]:
        options: list[SettingOption] = [{"value": "v-default", "label": "Default"}, {"value": "v-other", "label": "Other"}]
        return [{"key": self.voice_setting, "type": "select", "default": "v-default", "options": options}]


@dc.dataclass
class FakeJudge:
    needs_key: bool = False
    # Text -> the verdict for it. Text with no entry gets no verdict.
    verdicts: dict[str, Verdict] = dc.field(default_factory=dict)
    valid: bool = True
    asked: list[Question] = dc.field(default_factory=list)

    async def ask(self, question: Question, creds: dict[str, str], settings: Domain, http: aiohttp.ClientSession) -> Verdict | None:
        self.asked.append(question)
        text = question["user_saying"]
        return self.verdicts[text] if text in self.verdicts else None

    async def validate(self, creds: dict[str, str], settings: Domain) -> Validation:
        return (True, None) if self.valid else (False, "the fake says no")

    def settings_schema(self) -> list[SettingDef]:
        return []


# 80 ms of mic audio: the detector hears the phrase in a window that ends with WAKE_FRAME.
WAKE_FRAME = b"\x11" * wake.FRAME_BYTES
QUIET_FRAME = bytes(wake.FRAME_BYTES)


@dc.dataclass
class FakeDetector:
    windows: int = 0

    def score(self, window: bytes) -> float:
        self.windows += 1
        return 1.0 if window.endswith(WAKE_FRAME) else 0.0


@contextlib.asynccontextmanager
async def serving(app: web.Application) -> tp.AsyncIterator[TestClient]:
    async with TestClient(TestServer(app)) as client:
        yield client


@contextlib.asynccontextmanager
async def voice_service(data_dir: pl.Path) -> tp.AsyncIterator[TestClient]:
    async with serving(server.create_app(data_dir)) as client:
        yield client


async def opened(stt: FakeStt) -> None:
    """Wait until the session opens a stream (`stt.opened` is set), and clear it for the next one."""
    assert stt.opened is not None
    await asyncio.wait_for(stt.opened.wait(), FRAME_TIMEOUT_SECS)
    stt.opened.clear()


async def next_frame(ws: aiohttp.ClientWebSocketResponse) -> dict[str, JsonValue]:
    return await ws.receive_json(timeout=FRAME_TIMEOUT_SECS)


async def frames_until(ws: aiohttp.ClientWebSocketResponse, last_type: str) -> list[dict[str, JsonValue]]:
    """Every text frame up to and including the first one of `last_type`."""
    seen: list[dict[str, JsonValue]] = []
    while not seen or seen[-1]["type"] != last_type:
        seen.append(await next_frame(ws))
    return seen
