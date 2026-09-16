"""ElevenLabs providers: TTS (HTTP streaming) and Scribe STT (WebSocket realtime)."""

import asyncio
import base64
import json
import logging
import typing as tp
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from .base import SettingDef

logger = logging.getLogger("voice.elevenlabs")

ELEVENLABS_API = "https://api.elevenlabs.io"
ELEVENLABS_WS = "wss://api.elevenlabs.io"
MODEL_ID = "eleven_flash_v2_5"
DEFAULT_VOICE_ID = "FGY2WhTYpPnrIDTdsKH5"  # Laura

# One entry per audio_format the caller may request: the ElevenLabs output_format and the
# Content-Type to hand back. "mp3" feeds the app's <audio> element; "pcm" is raw signed
# 16-bit LE mono at 16 kHz, the frame format a phone-call consumer plays straight into a call.
AUDIO_FORMATS: dict[str, tuple[str, str]] = {
    "mp3": ("mp3_22050_32", "audio/mpeg"),
    "pcm": ("pcm_16000", "audio/l16;rate=16000"),
}

PREMADE_VOICES: list[dict[str, str]] = [
    {
        "id": "CwhRBWXzGAHq8TQ4Fs17",
        "name": "Roger",
        "description": "Laid-back, casual, American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/CwhRBWXzGAHq8TQ4Fs17/58ee3ff5-f6f2-4628-93b8-e38eb31806b0.mp3",
    },
    {
        "id": "EXAVITQu4vr4xnSDxMaL",
        "name": "Sarah",
        "description": "Mature, reassuring, American female",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/EXAVITQu4vr4xnSDxMaL/01a3e33c-6e99-4ee7-8543-ff2216a32186.mp3",
    },
    {
        "id": "FGY2WhTYpPnrIDTdsKH5",
        "name": "Laura",
        "description": "Enthusiastic, quirky, American female",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/FGY2WhTYpPnrIDTdsKH5/67341759-ad08-41a5-be6e-de12fe448618.mp3",
    },
    {
        "id": "IKne3meq5aSn9XLyUdCD",
        "name": "Charlie",
        "description": "Deep, confident, Australian male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/IKne3meq5aSn9XLyUdCD/102de6f2-22ed-43e0-a1f1-111fa75c5481.mp3",
    },
    {
        "id": "JBFqnCBsd6RMkjVDRZzb",
        "name": "George",
        "description": "Warm, captivating, British male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/JBFqnCBsd6RMkjVDRZzb/e6206d1a-0721-4787-aafb-06a6e705cac5.mp3",
    },
    {
        "id": "N2lVS1w4EtoT3dr4eOWO",
        "name": "Callum",
        "description": "Husky, American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/N2lVS1w4EtoT3dr4eOWO/ac833bd8-ffda-4938-9ebc-b0f99ca25481.mp3",
    },
    {
        "id": "SAz9YHcvj6GT2YYXdXww",
        "name": "River",
        "description": "Relaxed, neutral, informative",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/SAz9YHcvj6GT2YYXdXww/e6c95f0b-2227-491a-b3d7-2249240decb7.mp3",
    },
    {
        "id": "TX3LPaxmHKxFdv7VOQHJ",
        "name": "Liam",
        "description": "Energetic, young American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/TX3LPaxmHKxFdv7VOQHJ/63148076-6363-42db-aea8-31424308b92c.mp3",
    },
    {
        "id": "Xb7hH8MSUJpSbSDYk0k2",
        "name": "Alice",
        "description": "Clear, engaging, British female",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/Xb7hH8MSUJpSbSDYk0k2/d10f7534-11f6-41fe-a012-2de1e482d336.mp3",
    },
    {
        "id": "XrExE9yKIg1WjnnlVkGX",
        "name": "Matilda",
        "description": "Knowledgeable, professional, American female",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/XrExE9yKIg1WjnnlVkGX/b930e18d-6b4d-466e-bab2-0ae97c6d8535.mp3",
    },
    {
        "id": "bIHbv24MWmeRgasZH58o",
        "name": "Will",
        "description": "Relaxed optimist, young American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/bIHbv24MWmeRgasZH58o/8caf8f3d-ad29-4980-af41-53f20c72d7a4.mp3",
    },
    {
        "id": "cgSgspJ2msm6clMCkdW9",
        "name": "Jessica",
        "description": "Playful, bright, young American female",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/cgSgspJ2msm6clMCkdW9/56a97bf8-b69b-448f-846c-c3a11683d45a.mp3",
    },
    {
        "id": "cjVigY5qzO86Huf0OWal",
        "name": "Eric",
        "description": "Smooth, trustworthy, American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/cjVigY5qzO86Huf0OWal/d098fda0-6456-4030-b3d8-63aa048c9070.mp3",
    },
    {
        "id": "iP95p4xoKVk53GoZ742B",
        "name": "Chris",
        "description": "Charming, down-to-earth, American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/iP95p4xoKVk53GoZ742B/3f4bde72-cc48-40dd-829f-57fbf906f4d7.mp3",
    },
    {
        "id": "nPczCjzI2devNBz1zQrb",
        "name": "Brian",
        "description": "Deep, resonant, American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/nPczCjzI2devNBz1zQrb/2dd3e72c-4fd3-42f1-93ea-abc5d4e5aa1d.mp3",
    },
    {
        "id": "onwK4e9ZLuTAKqWW03F9",
        "name": "Daniel",
        "description": "Steady broadcaster, British male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/onwK4e9ZLuTAKqWW03F9/7eee0236-1a72-4b86-b303-5dcadc007ba9.mp3",
    },
    {
        "id": "pFZP5JQG7iQjIQuC4Bku",
        "name": "Lily",
        "description": "Velvety, British female",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/pFZP5JQG7iQjIQuC4Bku/89b68b35-b3dd-4348-a84a-a3c13a3c2b30.mp3",
    },
    {
        "id": "pNInz6obpgDQGcFmaJgB",
        "name": "Adam",
        "description": "Dominant, firm, American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/pNInz6obpgDQGcFmaJgB/d6905d7a-dd26-4187-bfff-1bd3a5ea7cac.mp3",
    },
    {
        "id": "pqHfZKP75CvOlQylNhV4",
        "name": "Bill",
        "description": "Wise, mature, American male",
        "preview": "https://storage.googleapis.com/eleven-public-prod/premade/voices/pqHfZKP75CvOlQylNhV4/d782b3ff-84ba-4029-848c-acf01285524d.mp3",
    },
]


class ElevenLabsTts:
    name = "elevenlabs"

    def settings_schema(self) -> list[SettingDef]:
        return [
            {
                "key": "selected_voice_id",
                "type": "select",
                "label": "voice",
                "description": "select a voice for speech synthesis",
                "default": DEFAULT_VOICE_ID,
                "options": [
                    {"value": v["id"], "label": v["name"], "description": v.get("description", ""), "preview": v.get("preview", "")}
                    for v in PREMADE_VOICES
                ],
            },
        ]

    async def speak(
        self,
        text: str,
        voice_id: str,
        creds: dict[str, str],
        request: web.Request,
        audio_format: str,
    ) -> web.StreamResponse:
        resolved = AUDIO_FORMATS.get(audio_format)
        if resolved is None:
            return web.json_response({"error": f"unsupported audio format: {audio_format}"}, status=400)
        output_format, content_type = resolved

        api_key = creds.get("api_key", "")
        url = f"{ELEVENLABS_API}/v1/text-to-speech/{voice_id}/stream"
        payload = {"text": text, "model_id": MODEL_ID, "output_format": output_format}

        session = aiohttp.ClientSession()
        try:
            upstream = await session.post(
                url,
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            )
        except (TimeoutError, aiohttp.ClientError) as e:
            await session.close()
            logger.error("elevenlabs request failed: %s", e)
            return web.json_response({"error": f"elevenlabs request failed: {e}"}, status=502)

        if upstream.status != 200:
            body_text = await upstream.text()
            upstream.release()
            await session.close()
            return web.json_response({"error": f"elevenlabs returned {upstream.status}", "body": body_text[:500]}, status=upstream.status)

        response = web.StreamResponse(status=200, headers={"Content-Type": content_type})
        await response.prepare(request)
        try:
            async for chunk in upstream.content.iter_any():
                await response.write(chunk)
            await response.write_eof()
        finally:
            upstream.release()
            await session.close()
        return response

    def premade_voices(self) -> list[dict]:
        return list(PREMADE_VOICES)

    async def subscription(self, creds: dict[str, str]) -> dict:
        api_key = creds.get("api_key", "")
        return await _fetch_subscription(api_key)

    async def validate(self, api_key: str) -> tuple[bool, str | None]:
        result = await _fetch_subscription(api_key)
        if "error" in result:
            msg = result["error"]
            if "401" in str(msg):
                return False, "invalid api key"
            return False, str(msg)
        return True, None


async def _fetch_subscription(api_key: str) -> dict:
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                f"{ELEVENLABS_API}/v1/user/subscription",
                headers={"xi-api-key": api_key},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp,
        ):
            body: tp.Any = await resp.json()
            if resp.status != 200:
                return {"error": f"status {resp.status}", "body": body}
            return body
    except (TimeoutError, aiohttp.ClientError) as e:
        return {"error": str(e)}


# --- Scribe v2 Realtime STT ---------------------------------------------------
# WebSocket streaming STT. Audio is PCM 16-bit LE mono at 16 kHz (the browser's frame
# format), sent base64-encoded inside input_audio_chunk JSON messages. commit_strategy=vad
# lets the server detect end-of-speech from trailing silence and emit a committed_transcript,
# which we map to the app's EndOfTurn. Silence window comes from the shared eot_timeout_ms.

SCRIBE_MODEL = "scribe_v2_realtime"
SCRIBE_SAMPLE_RATE = 16000
# Default trailing silence that ends a turn. Shorter than the shared 5 s config default because
# VAD silence IS the turn boundary here, so a snappy value keeps conversation turns responsive.
SCRIBE_DEFAULT_SILENCE_MS = 800

# Server-error message_types that should surface to the browser rather than be silently dropped.
_SCRIBE_ERROR_TYPES = frozenset(
    {
        "error",
        "auth_error",
        "quota_exceeded",
        "rate_limited",
        "unaccepted_terms",
        "input_error",
        "invalid_request",
        "transcriber_error",
        "session_time_limit_exceeded",
        "resource_exhausted",
        "queue_overflow",
    }
)

_WS_CLOSE = (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED)


class ElevenLabsScribe:
    name = "elevenlabs"

    def settings_schema(self) -> list[SettingDef]:
        return [
            {
                "key": "eot_timeout_ms",
                "type": "number",
                "label": "max silence timeout",
                "description": "trailing silence that ends a turn; VAD commits the transcript after this much quiet",
                "default": SCRIBE_DEFAULT_SILENCE_MS,
                "min": 500,
                "max": 10000,
                "step": 100,
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
                "description": "auto-detect the spoken language per turn",
                "default": False,
            },
        ]

    async def relay(
        self,
        browser_ws: web.WebSocketResponse,
        creds: dict[str, str],
        stt_domain: dict,
    ) -> None:
        api_key = creds.get("api_key")
        if not api_key:
            await browser_ws.close(code=1008, message=b"missing api_key")
            return

        url = _scribe_url(stt_domain)
        headers = {"xi-api-key": api_key}
        session = aiohttp.ClientSession()
        try:
            try:
                el_ws = await session.ws_connect(url, headers=headers, heartbeat=30.0)
            except (TimeoutError, aiohttp.ClientError) as e:
                logger.error("elevenlabs scribe connect failed: %s", e)
                await browser_ws.close(code=1011, message=f"scribe connect failed: {e}".encode())
                return
            tasks = [
                asyncio.create_task(_browser_to_scribe(browser_ws, el_ws)),
                asyncio.create_task(_scribe_to_browser(el_ws, browser_ws)),
            ]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in tasks:
                    t.cancel()
            finally:
                if not el_ws.closed:
                    await el_ws.close()
        finally:
            await session.close()

    async def usage(self, _creds: dict[str, str]) -> dict:
        # ElevenLabs meters STT against the same account subscription as TTS; the subscription
        # payload (returned by balance) already carries usage, so there is no separate call.
        return {}

    async def balance(self, creds: dict[str, str]) -> dict:
        return await _fetch_subscription(creds.get("api_key", ""))

    async def validate(self, api_key: str) -> tuple[bool, str | None]:
        result = await _fetch_subscription(api_key)
        if "error" in result:
            if "401" in str(result["error"]):
                return False, "invalid api key"
            return False, str(result["error"])
        return True, None


def _scribe_url(stt_domain: dict) -> str:
    from voice import config as voice_config

    eot_timeout_ms = int(stt_domain.get("eot_timeout_ms", SCRIBE_DEFAULT_SILENCE_MS))
    eot_timeout_ms = max(
        voice_config.EOT_TIMEOUT_MS_MIN,
        min(voice_config.EOT_TIMEOUT_MS_MAX, eot_timeout_ms),
    )
    silence_secs = round(eot_timeout_ms / 1000, 3)
    params: list[tuple[str, str]] = [
        ("model_id", SCRIBE_MODEL),
        ("audio_format", "pcm_16000"),
        ("commit_strategy", "vad"),
        ("vad_silence_threshold_secs", str(silence_secs)),
    ]
    if bool(stt_domain.get("multi_language")):
        params.append(("include_language_detection", "true"))
    keyterms = stt_domain.get("keyterms") or []
    if isinstance(keyterms, list):
        params.extend(("keyterms", term) for term in keyterms if isinstance(term, str))
    return f"{ELEVENLABS_WS}/v1/speech-to-text/realtime?{urlencode(params)}"


async def _browser_to_scribe(browser_ws: web.WebSocketResponse, el_ws: aiohttp.ClientWebSocketResponse) -> None:
    async for msg in browser_ws:
        if msg.type == aiohttp.WSMsgType.BINARY:
            payload = {
                "message_type": "input_audio_chunk",
                "audio_base_64": base64.b64encode(msg.data).decode("ascii"),
                "commit": False,
                "sample_rate": SCRIBE_SAMPLE_RATE,
            }
            await el_ws.send_str(json.dumps(payload))
        elif msg.type in _WS_CLOSE:
            break


async def _scribe_to_browser(el_ws: aiohttp.ClientWebSocketResponse, browser_ws: web.WebSocketResponse) -> None:
    """Translate Scribe realtime events into the app's TurnInfo protocol.

    partial_transcript -> interim transcript (StartOfTurn on the first of a turn);
    committed_transcript -> the finalized turn, followed by EndOfTurn. In vad commit mode a
    committed_transcript arrives when the speaker falls silent, so it is the turn boundary.
    """
    in_turn = False
    async for msg in el_ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            mt = data.get("message_type")
            if mt == "partial_transcript":
                text = (data.get("text") or "").strip()
                if text:
                    if not in_turn:
                        in_turn = True
                        await browser_ws.send_str(json.dumps({"type": "TurnInfo", "event": "StartOfTurn"}))
                    await browser_ws.send_str(json.dumps({"type": "TurnInfo", "transcript": text}))
            elif mt in ("committed_transcript", "committed_transcript_with_timestamps"):
                text = (data.get("text") or "").strip()
                if text and not in_turn:
                    in_turn = True
                    await browser_ws.send_str(json.dumps({"type": "TurnInfo", "event": "StartOfTurn"}))
                if text:
                    await browser_ws.send_str(json.dumps({"type": "TurnInfo", "transcript": text}))
                if in_turn:
                    await browser_ws.send_str(json.dumps({"type": "TurnInfo", "event": "EndOfTurn"}))
                    in_turn = False
            elif mt in _SCRIBE_ERROR_TYPES:
                await browser_ws.send_str(json.dumps({"type": "Error", "error": data.get("message") or mt}))
            # session_started, warning, insufficient_audio_activity, commit_throttled: ignored.
        elif msg.type in _WS_CLOSE:
            break
