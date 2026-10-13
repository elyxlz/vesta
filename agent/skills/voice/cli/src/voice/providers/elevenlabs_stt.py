"""ElevenLabs STT provider: Scribe on the realtime socket.

Scribe ends a turn on silence: the server commits the segment after `vad_silence_threshold_secs`
with no speech. SCRIBE_MODEL and SCRIBE_COMMIT_STRATEGY are the two values to change for a
Scribe model that predicts the end of a turn.
"""

import asyncio
import base64
import contextlib
import json
import logging
import pathlib as pl

import aiohttp

from voice.config import keyterms
from voice.settings import Domain, JsonValue, SettingDef

from .base import SttEvent, SttOpenError, SttStream, Validation
from .elevenlabs import ELEVENLABS_API, fetch_subscription
from .stream import SocketStream

logger = logging.getLogger("voice.elevenlabs_stt")

ELEVENLABS_WS = "wss://api.elevenlabs.io"
SCRIBE_MODEL = "scribe_v2_realtime"
SCRIBE_COMMIT_STRATEGY = "vad"
SCRIBE_FILE_MODEL = "scribe_v2"
SAMPLE_RATE = 16000
CONNECT_TIMEOUT_SECS = 10
FILE_TIMEOUT_SECS = 120

# The server accepts a lower silence threshold and then uses 0.5.
SILENCE_MIN_SECS = 0.5
SILENCE_MAX_SECS = 3.0
DEFAULT_SILENCE_SECS = 0.8

# The server refuses the connection for more terms, or for a longer term.
KEYTERMS_MAX = 50
KEYTERM_MAX_CHARS = 20


class ScribeStream(SocketStream):
    """One Scribe connection."""

    def __init__(self, session: aiohttp.ClientSession, ws: aiohttp.ClientWebSocketResponse) -> None:
        super().__init__(session, ws)
        self._commit_next = False
        self._last_text = ""

    async def send(self, pcm: bytes) -> None:
        chunk = {
            "message_type": "input_audio_chunk",
            "audio_base_64": base64.b64encode(pcm).decode(),
            "commit": self._commit_next,
            "sample_rate": SAMPLE_RATE,
        }
        self._commit_next = False
        with contextlib.suppress(ConnectionError):
            await self._ws.send_str(json.dumps(chunk))

    async def commit(self) -> None:
        # The commit flag rides on the next audio chunk, and the committed text follows it.
        self._commit_next = True

    def _event(self, message: dict[str, JsonValue]) -> SttEvent | None:
        kind = message["message_type"] if "message_type" in message else ""
        text = message["text"] if "text" in message and isinstance(message["text"], str) else ""
        if kind == "committed_transcript":
            self._last_text = ""
            return {"kind": "committed", "text": text}
        if kind != "partial_transcript" or text == self._last_text:
            return None
        self._last_text = text
        return {"kind": "transcription", "text": text}


class ElevenLabsStt:
    name = "elevenlabs"
    needs_key = True

    def settings_schema(self) -> list[SettingDef]:
        return [
            {
                "key": "vad_silence_threshold_secs",
                "type": "number",
                "label": "silence before a turn ends",
                "description": "how long you must stay silent before your turn ends; lower answers faster, higher allows longer pauses",
                "default": DEFAULT_SILENCE_SECS,
                "min": SILENCE_MIN_SECS,
                "max": SILENCE_MAX_SECS,
                "step": 0.1,
                "unit": "s",
            },
        ]

    async def open(self, creds: dict[str, str], settings: Domain) -> SttStream:
        session, ws = await _connect(creds, settings)
        return ScribeStream(session, ws)

    async def validate(self, creds: dict[str, str], settings: Domain) -> Validation:
        try:
            session, ws = await _connect(creds, settings)
        except SttOpenError as e:
            return False, str(e)
        await ws.close()
        await session.close()
        return True, None

    async def transcribe_file(self, audio_path: pl.Path, creds: dict[str, str], language: str | None) -> str:
        form = aiohttp.FormData()
        form.add_field("model_id", SCRIBE_FILE_MODEL)
        if language:
            form.add_field("language_code", language)
        form.add_field("file", await asyncio.to_thread(audio_path.read_bytes), filename=audio_path.name)
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                f"{ELEVENLABS_API}/v1/speech-to-text",
                data=form,
                headers={"xi-api-key": _api_key(creds)},
                timeout=aiohttp.ClientTimeout(total=FILE_TIMEOUT_SECS),
            ) as resp,
        ):
            if resp.status != 200:
                raise RuntimeError(f"elevenlabs returned {resp.status}: {(await resp.text()).strip()}")
            body = await resp.json()
            return body["text"].strip() if "text" in body and isinstance(body["text"], str) else ""

    async def usage(self, creds: dict[str, str]) -> dict[str, JsonValue]:
        return await fetch_subscription(_api_key(creds))

    async def balance(self, _creds: dict[str, str]) -> dict[str, JsonValue]:
        return {}


def _api_key(creds: dict[str, str]) -> str:
    return creds["api_key"] if "api_key" in creds else ""


def _silence_secs(settings: Domain) -> float:
    value = settings["vad_silence_threshold_secs"] if "vad_silence_threshold_secs" in settings else DEFAULT_SILENCE_SECS
    if isinstance(value, bool) or not isinstance(value, int | float):
        return DEFAULT_SILENCE_SECS
    return max(SILENCE_MIN_SECS, min(SILENCE_MAX_SECS, float(value)))


def _query(settings: Domain) -> list[tuple[str, str]]:
    terms = keyterms(settings)
    fitting = [term for term in terms if len(term) <= KEYTERM_MAX_CHARS][:KEYTERMS_MAX]
    if len(fitting) < len(terms):
        logger.warning(
            "scribe takes %s key terms of %s characters or less; not sent: %s",
            KEYTERMS_MAX,
            KEYTERM_MAX_CHARS,
            [t for t in terms if t not in fitting],
        )
    return [
        ("model_id", SCRIBE_MODEL),
        ("commit_strategy", SCRIBE_COMMIT_STRATEGY),
        ("audio_format", f"pcm_{SAMPLE_RATE}"),
        ("vad_silence_threshold_secs", str(_silence_secs(settings))),
        *(("keyterms", term) for term in fitting),
    ]


async def _connect(creds: dict[str, str], settings: Domain) -> tuple[aiohttp.ClientSession, aiohttp.ClientWebSocketResponse]:
    """Open the Scribe socket and read its first message, which decides the open:
    `session_started` is success, `rate_limited` is the plan's limit on sessions at the same
    time, and every other first message is a refusal."""
    session = aiohttp.ClientSession()
    try:
        ws = await session.ws_connect(
            f"{ELEVENLABS_WS}/v1/speech-to-text/realtime",
            params=_query(settings),
            headers={"xi-api-key": _api_key(creds)},
            timeout=aiohttp.ClientWSTimeout(ws_close=CONNECT_TIMEOUT_SECS),
        )
        first = await ws.receive(timeout=CONNECT_TIMEOUT_SECS)
    except (TimeoutError, aiohttp.ClientError) as e:
        await session.close()
        raise SttOpenError("failed", f"elevenlabs connect failed: {e}") from e
    kind = ""
    if first.type == aiohttp.WSMsgType.TEXT:
        data = json.loads(first.data)
        kind = data["message_type"] if "message_type" in data else ""
    if kind == "session_started":
        return session, ws
    await ws.close()
    await session.close()
    if kind == "rate_limited":
        raise SttOpenError("limit", "elevenlabs refused the connection: too many sessions for this plan")
    if kind == "auth_error":
        raise SttOpenError("failed", "invalid api key")
    raise SttOpenError("failed", f"elevenlabs refused the connection: {kind or 'no answer'}")
