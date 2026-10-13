"""Both TTS providers, one contract: each adapter runs against a fake of its provider's HTTP API."""

import asyncio
import contextlib
import dataclasses as dc
import typing as tp

import aiohttp
import pytest
from aiohttp import web
from voice.providers import deepgram, deepgram_tts, elevenlabs
from voice.providers.base import TtsError, TtsProvider
from voice.settings import JsonValue

from .fakes import serving

CREDS = {"api_key": "good-key"}


@dc.dataclass
class FakeApi:
    """One provider's HTTP API in a test: what it answers, and the requests it saw."""

    status: int = 200
    error_body: dict[str, JsonValue] = dc.field(default_factory=dict)
    requests: list[dict[str, JsonValue]] = dc.field(default_factory=list)

    async def handle(self, request: web.Request) -> web.StreamResponse:
        body = await request.json()
        self.requests.append({"path": request.path, "query": dict(request.query), "body": body, "headers": dict(request.headers)})
        if self.status != 200:
            return web.json_response(self.error_body, status=self.status)
        response = web.StreamResponse()
        await response.prepare(request)
        # The audio of a request names its text, so a test can see the order of the parts.
        for part in (b"<", str(body["text"])[:8].encode(), b">"):
            await response.write(part)
        await response.write_eof()
        return response


@dc.dataclass
class Row:
    name: str
    provider: TtsProvider
    module: tp.Any
    path: str
    voice: str
    # Play format -> what the request must carry for it.
    expected: dict[str, dict[str, str]]
    request_format: tp.Callable[[dict[str, JsonValue]], dict[str, str]]
    bad_key_status: int
    bad_key_body: dict[str, JsonValue]


def _elevenlabs_format(request: dict[str, JsonValue]) -> dict[str, str]:
    body, query = request["body"], request["query"]
    assert isinstance(body, dict)
    assert isinstance(query, dict)
    assert "output_format" not in body
    return {"output_format": str(query["output_format"]), "model_id": str(body["model_id"])}


def _deepgram_format(request: dict[str, JsonValue]) -> dict[str, str]:
    query = request["query"]
    assert isinstance(query, dict)
    return {key: str(value) for key, value in query.items() if key != "model"}


ROWS = [
    Row(
        name="elevenlabs",
        provider=elevenlabs.ElevenLabsTts(),
        module=elevenlabs,
        path="/v1/text-to-speech/{voice}/stream",
        voice="FGY2WhTYpPnrIDTdsKH5",
        expected={
            "mp3_22050": {"output_format": "mp3_22050_32", "model_id": "eleven_v4_turbo"},
            "mp3_44100": {"output_format": "mp3_44100_128", "model_id": "eleven_v4_turbo"},
            "pcm_16000": {"output_format": "pcm_16000", "model_id": "eleven_v4_turbo"},
            "pcm_22050": {"output_format": "pcm_22050", "model_id": "eleven_v4_turbo"},
            "pcm_24000": {"output_format": "pcm_24000", "model_id": "eleven_v4_turbo"},
            "ulaw_8000": {"output_format": "ulaw_8000", "model_id": "eleven_v4_turbo"},
            "opus_48000": {"output_format": "opus_48000_64", "model_id": "eleven_v4_turbo"},
        },
        request_format=_elevenlabs_format,
        bad_key_status=401,
        bad_key_body={"detail": {"status": "invalid_api_key", "message": "Invalid API key"}},
    ),
    Row(
        name="deepgram",
        provider=deepgram_tts.DeepgramTts(),
        module=deepgram_tts,
        path="/v1/speak",
        voice="aura-2-melia-it",
        expected={
            "mp3_22050": {"encoding": "mp3"},
            "pcm_16000": {"encoding": "linear16", "container": "none", "sample_rate": "16000"},
            "pcm_24000": {"encoding": "linear16", "container": "none", "sample_rate": "24000"},
            "ulaw_8000": {"encoding": "mulaw", "container": "none", "sample_rate": "8000"},
        },
        request_format=_deepgram_format,
        bad_key_status=401,
        bad_key_body={"err_code": "INVALID_AUTH", "err_msg": "Invalid credentials.", "request_id": "r"},
    ),
]
BY_NAME = {row.name: row for row in ROWS}
FORMAT_CASES = [(row, audio_format) for row in ROWS for audio_format in sorted(row.expected)]


@contextlib.asynccontextmanager
async def provider_api(row: Row, monkeypatch: pytest.MonkeyPatch, api: FakeApi) -> tp.AsyncIterator[aiohttp.ClientSession]:
    app = web.Application()
    app.router.add_post(row.path, api.handle)
    async with serving(app) as client, aiohttp.ClientSession() as http:
        base = f"http://{client.host}:{client.port}"
        monkeypatch.setattr(row.module, "ELEVENLABS_API" if row.name == "elevenlabs" else "DEEPGRAM_API", base)
        yield http


async def _audio(row: Row, http: aiohttp.ClientSession, text: str, audio_format: str = "mp3_22050") -> bytes:
    return b"".join([chunk async for chunk in row.provider.synthesize(text, row.voice, audio_format, CREDS, {}, http)])


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_the_audio_bytes_come_in_order(row: Row, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        async with provider_api(row, monkeypatch, FakeApi()) as http:
            assert await _audio(row, http, "Hello.") == b"<Hello.>"

    asyncio.run(scenario())


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_the_formats_a_provider_lists_are_the_formats_it_maps(row: Row) -> None:
    assert row.provider.formats == frozenset(row.expected)


@pytest.mark.parametrize(("row", "audio_format"), FORMAT_CASES, ids=[f"{row.name}-{audio_format}" for row, audio_format in FORMAT_CASES])
def test_each_format_gives_the_request_that_makes_it(row: Row, audio_format: str, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        api = FakeApi()
        async with provider_api(row, monkeypatch, api) as http:
            await _audio(row, http, "Hello.", audio_format)

        assert row.request_format(api.requests[0]) == row.expected[audio_format]

    asyncio.run(scenario())


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_a_refused_key_raises_a_tts_error(row: Row, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        async with provider_api(row, monkeypatch, FakeApi(status=row.bad_key_status, error_body=row.bad_key_body)) as http:
            with pytest.raises(TtsError, match="401"):
                await _audio(row, http, "Hello.")

    asyncio.run(scenario())


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_too_many_requests_at_the_same_time_raises_a_tts_error(row: Row, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        busy = FakeApi(status=429, error_body={"err_code": "Too Many Requests", "err_msg": "Please try again later."})
        async with provider_api(row, monkeypatch, busy) as http:
            with pytest.raises(TtsError, match="429"):
                await _audio(row, http, "Hello.")

    asyncio.run(scenario())


def test_the_voice_of_each_provider_goes_where_that_provider_reads_it(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        eleven, aura = FakeApi(), FakeApi()
        async with provider_api(BY_NAME["elevenlabs"], monkeypatch, eleven) as http:
            await _audio(BY_NAME["elevenlabs"], http, "Hello.")
        async with provider_api(BY_NAME["deepgram"], monkeypatch, aura) as http:
            await _audio(BY_NAME["deepgram"], http, "Ciao.")

        assert eleven.requests[0]["path"] == "/v1/text-to-speech/FGY2WhTYpPnrIDTdsKH5/stream"
        assert aura.requests[0]["query"] == {"model": "aura-2-melia-it", "encoding": "mp3"}
        assert aura.requests[0]["body"] == {"text": "Ciao."}

    asyncio.run(scenario())


def test_deepgram_splits_a_long_text_at_sentence_ends_and_joins_the_audio_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    sentences = [f"Sentence number {index:03d} is here." for index in range(150)]
    text = " ".join(sentences)

    async def scenario() -> None:
        api = FakeApi()
        async with provider_api(BY_NAME["deepgram"], monkeypatch, api) as http:
            audio = await _audio(BY_NAME["deepgram"], http, text)

        parts = [str(tp.cast(dict[str, str], request["body"])["text"]) for request in api.requests]
        assert len(parts) == 3
        assert all(len(part) <= deepgram_tts.AURA_MAX_CHARS for part in parts)
        assert all(part.endswith(".") for part in parts)
        assert " ".join(parts) == text
        assert audio == b"".join(b"<" + part[:8].encode() + b">" for part in parts)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("text", "limit", "parts"),
    [
        ("One. Two. Three.", 10, ["One. Two.", "Three."]),
        ("Short.", 2000, ["Short."]),
        ("no sentence end in this long line", 12, ["no sentence", "end in this", "long line"]),
        ("abcdefghij", 4, ["abcd", "efgh", "ij"]),
        ("", 10, []),
    ],
)
def test_split_text_keeps_each_part_inside_the_limit(text: str, limit: int, parts: list[str]) -> None:
    assert deepgram_tts.split_text(text, limit) == parts


def test_the_deepgram_check_synthesizes_two_characters(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        api = FakeApi()
        async with provider_api(BY_NAME["deepgram"], monkeypatch, api):
            assert await BY_NAME["deepgram"].provider.validate(CREDS, {}) == (True, None)

        assert api.requests[0]["body"] == {"text": "ok"}

    asyncio.run(scenario())


def test_the_deepgram_check_names_an_invalid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        row = BY_NAME["deepgram"]
        async with provider_api(row, monkeypatch, FakeApi(status=401, error_body=row.bad_key_body)):
            assert await row.provider.validate({"api_key": "bad"}, {}) == (False, "invalid api key")

    asyncio.run(scenario())


def test_the_deepgram_check_reports_a_key_with_no_permission_for_speech(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        denied = FakeApi(
            status=403, error_body={"err_code": "INSUFFICIENT_PERMISSIONS", "err_msg": "Project does not have access to the requested model."}
        )
        async with provider_api(BY_NAME["deepgram"], monkeypatch, denied):
            ok, message = await BY_NAME["deepgram"].provider.validate(CREDS, {})

        assert ok is False
        assert message == "INSUFFICIENT_PERMISSIONS: Project does not have access to the requested model."

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("probe", "verdict"),
    [
        ({"tier": "creator"}, (True, None)),
        ({"error": "status 401", "body": {"detail": {"status": "missing_permissions", "message": "no user_read"}}}, (True, None)),
        ({"error": "status 401", "body": {"detail": {"status": "invalid_api_key", "message": "Invalid API key"}}}, (False, "invalid api key")),
        ({"error": "Cannot connect to host"}, (False, "Cannot connect to host")),
    ],
)
def test_an_elevenlabs_key_with_limited_permissions_is_a_valid_key(probe: dict[str, JsonValue], verdict: tuple[bool, str | None]) -> None:
    assert elevenlabs.subscription_validation(probe) == verdict


def test_every_aura_voice_is_an_option_of_the_deepgram_voice_setting() -> None:
    provider = deepgram_tts.DeepgramTts()
    options = provider.settings_schema()[0]["options"]

    assert provider.voice_setting == "aura_voice"
    assert len(options) == 90
    assert {"value": "aura-2-melia-it", "label": "Melia", "description": "Italian, feminine: clear, comfortable, engaging"} in options


def test_the_deepgram_subscription_is_the_balance_of_the_account(monkeypatch: pytest.MonkeyPatch) -> None:
    async def projects(_request: web.Request) -> web.Response:
        return web.json_response({"projects": [{"project_id": "p1"}]})

    async def balances(request: web.Request) -> web.Response:
        assert request.headers["Authorization"] == "Token dg-key"
        return web.json_response({"balances": [{"amount": 12.5, "units": "usd"}]})

    async def scenario() -> dict[str, JsonValue]:
        app = web.Application()
        app.router.add_get("/v1/projects", projects)
        app.router.add_get("/v1/projects/p1/balances", balances)
        async with serving(app) as client:
            monkeypatch.setattr(deepgram, "DEEPGRAM_API", str(client.make_url("")).rstrip("/"))
            return await deepgram_tts.DeepgramTts().subscription({"api_key": "dg-key"})

    assert asyncio.run(scenario()) == {"balances": [{"amount": 12.5, "units": "usd"}]}
