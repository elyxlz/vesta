"""Deepgram STT provider: Flux on the v2 realtime socket.

Flux predicts the end of a turn from the words and the silence, so `open` maps its `EndOfTurn`
to `committed`.
"""

import asyncio
import contextlib
import pathlib as pl
from urllib.parse import urlencode

import aiohttp

from voice.config import keyterms
from voice.settings import Domain, JsonValue, SettingDef, clamped

from .base import Amount, SttEvent, SttOpenError, SttStream, Usage, Validation, api_key, no_usage, number_in
from .stream import SocketStream, check_open

DEEPGRAM_API = "https://api.deepgram.com"
DEEPGRAM_WS = "wss://api.deepgram.com"
MODEL = "flux-general-en"
MODEL_MULTI = "flux-general-multi"
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
                "key": "multi_language",
                "type": "bool",
                "label": "multi-language detection",
                "description": "automatically detect spoken language per utterance (English, Italian, and more)",
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

    async def usage(self, creds: dict[str, str]) -> Usage:
        key = api_key(creds)
        project_id = await self._cached_project_id(key)
        if not project_id:
            return no_usage()
        url = f"{DEEPGRAM_API}/v1/projects/{project_id}/usage/breakdown?endpoint=listen"
        breakdown, left = await asyncio.gather(_get_json(url, {"Authorization": f"Token {key}"}), _balance_left(key, project_id))
        return {"used": _hours_used(breakdown), "left": left}


async def account_balance(key: str) -> Amount | None:
    """What is left on the project that owns this key."""
    project = await _project_id(key)
    return await _balance_left(key, project) if project else None


async def _balance_left(key: str, project: str) -> Amount | None:
    body = await _get_json(f"{DEEPGRAM_API}/v1/projects/{project}/balances", {"Authorization": f"Token {key}"})
    balances = body["balances"] if "balances" in body else None
    if not isinstance(balances, list) or not balances or not isinstance(balance := balances[0], dict):
        return None
    amount = number_in(balance, "amount")
    units = balance["units"] if "units" in balance else None
    if amount is None or not isinstance(units, str):
        return None
    return {"amount": amount, "unit": units.lower()}


def _hours_used(breakdown: dict[str, JsonValue]) -> Amount | None:
    """The hours of all the results of a usage breakdown."""
    results = breakdown["results"] if "results" in breakdown else None
    if not isinstance(results, list):
        return None
    hours = [number_in(result, "hours") for result in results]
    return {"amount": sum(h for h in hours if h is not None), "unit": "hours"}


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
        ("model", MODEL_MULTI if multi_language else MODEL),
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


def _prerecorded_params(language: str | None) -> list[tuple[str, str]]:
    """Nova-3 with smart formatting; `multi` makes Deepgram detect the spoken language."""
    return [("model", PRERECORDED_MODEL), ("smart_format", "true"), ("language", language or "multi")]


def _prerecorded_transcript(body: dict) -> str:
    try:
        return body["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
    except (KeyError, IndexError, TypeError):
        return ""


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
