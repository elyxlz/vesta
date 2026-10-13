"""Deepgram STT provider: Flux on the v2 realtime socket.

Flux predicts the end of a turn from the words and the silence, so `open` maps its `EndOfTurn`
to `committed`. `relay` is the pass-through socket of the `/stt/listen` route, which speaks the
Deepgram wire format to its client and uses Nova-3 on v1 for multi-language.
"""

import asyncio
import contextlib
import json
import logging
import pathlib as pl
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from voice.config import keyterms
from voice.settings import Domain, JsonValue, SettingDef, clamped

from .base import SttEvent, SttOpenError, SttStream, Validation, api_key
from .stream import SocketStream, check_open

logger = logging.getLogger("voice.deepgram")

DEEPGRAM_API = "https://api.deepgram.com"
DEEPGRAM_WS = "wss://api.deepgram.com"
MODEL = "flux-general-en"
FLUX_MODEL_MULTI = "flux-general-multi"
MODEL_MULTI = "nova-3"
ENCODING = "linear16"
SAMPLE_RATE = 16000
HEARTBEAT_SECS = 30.0
CONNECT_TIMEOUT_SECS = 10

DEFAULT_EOT_THRESHOLD = 0.8
DEFAULT_EOT_TIMEOUT_MS = 5000
EOT_THRESHOLD_MIN = 0.5
EOT_THRESHOLD_MAX = 0.9
EOT_TIMEOUT_MS_MIN = 500
EOT_TIMEOUT_MS_MAX = 10000

# Prerecorded (one-shot file) transcription, the `transcribe` command's provider path.
PRERECORDED_MODEL = "nova-3"
PRERECORDED_TIMEOUT_SECS = 120


class FluxStream(SocketStream):
    """One Flux connection. `commit` puts its own `committed` in order with Flux's events."""

    def __init__(self, session: aiohttp.ClientSession, ws: aiohttp.ClientWebSocketResponse) -> None:
        super().__init__(session, ws)
        self._turn_open = False
        self._transcript = ""
        # commit() ended the turn here, and Flux has not ended it yet: its events for that
        # turn, up to and including its EndOfTurn, belong to text that is already committed.
        self._dropping = False

    async def send(self, pcm: bytes) -> None:
        with contextlib.suppress(ConnectionError):
            await self._ws.send_bytes(pcm)

    async def commit(self) -> None:
        text = self._transcript if self._turn_open and not self._dropping else ""
        self._dropping = self._turn_open
        self._transcript = ""
        self._emit({"kind": "committed", "text": text})

    def _event(self, message: dict[str, JsonValue]) -> SttEvent | None:
        if "type" not in message or message["type"] != "TurnInfo":
            return None
        transcript = str(message["transcript"])
        ended = message["event"] == "EndOfTurn"
        if self._dropping:
            if ended:
                self._dropping = False
                self._turn_open = False
            return None
        if ended:
            self._turn_open = False
            self._transcript = ""
            return {"kind": "committed", "text": transcript}
        # Flux also reports on silence: a turn is open once it started or has words.
        self._turn_open = self._turn_open or message["event"] == "StartOfTurn" or bool(transcript)
        if transcript == self._transcript:
            return None
        self._transcript = transcript
        return {"kind": "transcription", "text": transcript}


class DeepgramStt:
    needs_key = True

    def settings_schema(self) -> list[SettingDef]:
        return [
            {
                "key": "eot_threshold",
                "type": "number",
                "label": "end-of-turn sensitivity",
                "description": "lower finalizes turns faster; higher waits for more confidence before ending the turn",
                "default": DEFAULT_EOT_THRESHOLD,
                "min": EOT_THRESHOLD_MIN,
                "max": EOT_THRESHOLD_MAX,
                "step": 0.05,
            },
            {
                "key": "eot_timeout_ms",
                "type": "number",
                "label": "max silence timeout",
                "description": "max silence before forcing end of turn; timer resets when speech resumes",
                "default": DEFAULT_EOT_TIMEOUT_MS,
                "min": EOT_TIMEOUT_MS_MIN,
                "max": EOT_TIMEOUT_MS_MAX,
                "step": 500,
                "unit": "ms",
            },
            {
                "key": "interrupt_tts",
                "type": "bool",
                "label": "interrupt speech on talk",
                "description": "stop text-to-speech playback when you start speaking",
                "default": True,
            },
            {
                "key": "multi_language",
                "type": "bool",
                "label": "multi-language detection",
                "description": "automatically detect spoken language per utterance (English, Italian, and more); uses Nova-3 model",
                "default": False,
            },
        ]

    def __init__(self) -> None:
        # Cache project_id per api_key so status checks don't hit /v1/projects
        # twice per request (usage + balance both need it).
        self._project_id_cache: dict[str, str] = {}

    async def open(self, creds: dict[str, str], settings: Domain) -> SttStream:
        session, ws = await _connect_flux(creds, settings)
        return FluxStream(session, ws)

    async def validate(self, creds: dict[str, str], settings: Domain) -> Validation:
        return await check_open(self.open(creds, settings))

    async def transcribe_file(self, audio_path: pl.Path, creds: dict[str, str], language: str | None) -> str:
        if "api_key" not in creds or not creds["api_key"]:
            raise ValueError("missing deepgram api_key")
        url = f"{DEEPGRAM_API}/v1/listen?{urlencode(_prerecorded_params(language))}"
        headers = {"Authorization": f"Token {creds['api_key']}", "Content-Type": "audio/*"}
        audio = await asyncio.to_thread(audio_path.read_bytes)
        async with (
            aiohttp.ClientSession() as session,
            session.post(url, data=audio, headers=headers, timeout=aiohttp.ClientTimeout(total=PRERECORDED_TIMEOUT_SECS)) as resp,
        ):
            if resp.status != 200:
                raise RuntimeError(f"deepgram returned {resp.status}: {(await resp.text()).strip()}")
            return _prerecorded_transcript(await resp.json())

    async def _cached_project_id(self, key: str) -> str | None:
        if (cached := self._project_id_cache.get(key)) is not None:
            return cached
        project_id = await _project_id(key)
        if project_id:
            self._project_id_cache[key] = project_id
        return project_id

    async def usage(self, creds: dict[str, str]) -> dict[str, JsonValue]:
        key = api_key(creds)
        project_id = await self._cached_project_id(key)
        if not project_id:
            return {"error": "no project"}
        url = f"{DEEPGRAM_API}/v1/projects/{project_id}/usage/breakdown?endpoint=listen"
        return await _get_json(url, {"Authorization": f"Token {key}"})

    async def balance(self, creds: dict[str, str]) -> dict[str, JsonValue]:
        key = api_key(creds)
        project_id = await self._cached_project_id(key)
        if not project_id:
            return {"error": "no project"}
        url = f"{DEEPGRAM_API}/v1/projects/{project_id}/balances"
        return await _get_json(url, {"Authorization": f"Token {key}"})


async def relay(
    browser_ws: web.WebSocketResponse,
    creds: dict[str, str],
    stt_domain: Domain,
) -> None:
    key = api_key(creds)
    if not key:
        await browser_ws.close(code=1008, message=b"missing api_key")
        return

    multi_language = "multi_language" in stt_domain and bool(stt_domain["multi_language"])
    url = _nova_url(stt_domain) if multi_language else _flux_url(stt_domain)
    headers = {"Authorization": f"Token {key}"}

    session = aiohttp.ClientSession()
    try:
        try:
            dg_ws = await session.ws_connect(url, headers=headers, heartbeat=HEARTBEAT_SECS)
        except (TimeoutError, aiohttp.ClientError) as e:
            logger.error("deepgram connect failed: %s", e)
            await browser_ws.close(code=1011, message=f"deepgram connect failed: {e}".encode())
            return

        pump = _translate_v1_to_browser if multi_language else _pipe_to_browser
        tasks = [
            asyncio.create_task(_browser_to_deepgram(browser_ws, dg_ws)),
            asyncio.create_task(pump(dg_ws, browser_ws)),
        ]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in tasks:
                t.cancel()
        finally:
            if not dg_ws.closed:
                await dg_ws.close()
    finally:
        await session.close()


def _eot_params(settings: Domain) -> tuple[float, int]:
    """The end-of-turn threshold and timeout to send, held inside the range Flux accepts."""
    return (
        clamped(settings, "eot_threshold", DEFAULT_EOT_THRESHOLD, EOT_THRESHOLD_MIN, EOT_THRESHOLD_MAX),
        int(clamped(settings, "eot_timeout_ms", DEFAULT_EOT_TIMEOUT_MS, EOT_TIMEOUT_MS_MIN, EOT_TIMEOUT_MS_MAX)),
    )


def _flux_url(settings: Domain) -> str:
    multi_language = "multi_language" in settings and bool(settings["multi_language"])
    eot_threshold, eot_timeout_ms = _eot_params(settings)
    params: list[tuple[str, str]] = [
        ("model", FLUX_MODEL_MULTI if multi_language else MODEL),
        ("encoding", ENCODING),
        ("sample_rate", str(SAMPLE_RATE)),
        ("eot_threshold", str(eot_threshold)),
        ("eot_timeout_ms", str(eot_timeout_ms)),
        *(("keyterm", term) for term in keyterms(settings)),
    ]
    return f"{DEEPGRAM_WS}/v2/listen?{urlencode(params)}"


async def _connect_flux(creds: dict[str, str], settings: Domain) -> tuple[aiohttp.ClientSession, aiohttp.ClientWebSocketResponse]:
    """Open the Flux socket. A refused handshake is an SttOpenError: `limit` for 429, the
    provider's limit on sessions at the same time, and `failed` for every other refusal."""
    key = api_key(creds)
    session = aiohttp.ClientSession()
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT_SECS):
            ws = await session.ws_connect(
                _flux_url(settings),
                headers={"Authorization": f"Token {key}"},
                heartbeat=HEARTBEAT_SECS,
            )
    except aiohttp.WSServerHandshakeError as e:
        await session.close()
        if e.status == 429:
            raise SttOpenError("limit", "deepgram refused the connection: too many sessions") from e
        if e.status in (401, 403):
            raise SttOpenError("failed", "invalid api key") from e
        raise SttOpenError("failed", f"deepgram refused the connection: {e.status}") from e
    except (TimeoutError, aiohttp.ClientError) as e:
        await session.close()
        raise SttOpenError("failed", f"deepgram connect failed: {e}") from e
    return session, ws


def _nova_url(stt_domain: Domain) -> str:
    """The multi-language socket of `relay`: Nova-3 only works on /v1/listen, and v2 returns 400
    for a model that is not Flux."""
    _eot_threshold, eot_timeout_ms = _eot_params(stt_domain)
    params: list[tuple[str, str]] = [
        ("model", MODEL_MULTI),
        ("language", "multi"),
        ("encoding", ENCODING),
        ("sample_rate", str(SAMPLE_RATE)),
        ("interim_results", "true"),
        ("utterance_end_ms", str(eot_timeout_ms)),
        *(("keywords", term) for term in keyterms(stt_domain)),
    ]
    return f"{DEEPGRAM_WS}/v1/listen?{urlencode(params)}"


def _prerecorded_params(language: str | None) -> list[tuple[str, str]]:
    """Nova-3 with smart formatting; `multi` makes Deepgram detect the spoken language."""
    return [("model", PRERECORDED_MODEL), ("smart_format", "true"), ("language", language or "multi")]


def _prerecorded_transcript(body: dict) -> str:
    try:
        return body["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
    except (KeyError, IndexError, TypeError):
        return ""


async def _browser_to_deepgram(browser_ws: web.WebSocketResponse, dg_ws: aiohttp.ClientWebSocketResponse) -> None:
    async for msg in browser_ws:
        if msg.type == aiohttp.WSMsgType.BINARY:
            await dg_ws.send_bytes(msg.data)
        elif msg.type == aiohttp.WSMsgType.TEXT:
            await dg_ws.send_str(msg.data)
        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
            break


async def _forward_results(browser_ws: web.WebSocketResponse, data: dict, accumulated: str, in_turn: bool) -> tuple[str, bool]:
    alts = (data.get("channel") or {}).get("alternatives") or []
    transcript = alts[0].get("transcript", "") if alts else ""
    is_final = data.get("is_final", False)
    if transcript and not in_turn:
        in_turn = True
        await browser_ws.send_str(json.dumps({"type": "TurnInfo", "event": "StartOfTurn"}))
    if transcript:
        display = (accumulated + " " + transcript).strip() if accumulated else transcript
        await browser_ws.send_str(json.dumps({"type": "TurnInfo", "transcript": display}))
    if is_final and transcript:
        accumulated = (accumulated + " " + transcript).strip() if accumulated else transcript
    return accumulated, in_turn


async def _translate_v1_to_browser(dg_ws: aiohttp.ClientWebSocketResponse, browser_ws: web.WebSocketResponse) -> None:
    """v1 emits Results + UtteranceEnd; translate to the TurnInfo format the app expects."""
    accumulated = ""
    in_turn = False
    async for msg in dg_ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                await browser_ws.send_str(msg.data)
                continue
            msg_type = data.get("type")
            if msg_type == "Results":
                accumulated, in_turn = await _forward_results(browser_ws, data, accumulated, in_turn)
            elif msg_type == "UtteranceEnd":
                if in_turn:
                    await browser_ws.send_str(json.dumps({"type": "TurnInfo", "event": "EndOfTurn"}))
                    accumulated = ""
                    in_turn = False
            elif msg_type in ("Error", "ConfigureFailure"):
                await browser_ws.send_str(msg.data)
        elif msg.type == aiohttp.WSMsgType.BINARY:
            await browser_ws.send_bytes(msg.data)
        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
            break


async def _pipe_to_browser(dg_ws: aiohttp.ClientWebSocketResponse, browser_ws: web.WebSocketResponse) -> None:
    async for msg in dg_ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            await browser_ws.send_str(msg.data)
        elif msg.type == aiohttp.WSMsgType.BINARY:
            await browser_ws.send_bytes(msg.data)
        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
            break


async def _project_id(key: str) -> str | None:
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                f"{DEEPGRAM_API}/v1/projects",
                headers={"Authorization": f"Token {key}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp,
        ):
            if resp.status != 200:
                return None
            body = await resp.json()
            projects = body.get("projects") or []
            if not projects:
                return None
            return projects[0].get("project_id")
    except (TimeoutError, aiohttp.ClientError):
        return None


async def _get_json(url: str, headers: dict[str, str]) -> dict[str, JsonValue]:
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp,
        ):
            body: dict[str, JsonValue] = await resp.json()
            if resp.status != 200:
                return {"error": f"status {resp.status}", "body": body}
            return body
    except (TimeoutError, aiohttp.ClientError) as e:
        return {"error": str(e)}
