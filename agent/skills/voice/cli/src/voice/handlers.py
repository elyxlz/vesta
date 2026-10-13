"""The HTTP routes of the voice service: status, settings, and the stock app's audio routes.

`/stt/listen` and the `/tts/` audio routes serve the stock app and the stock skills. A client of
its own uses the engine socket (engine/session.py).
"""

import asyncio
import logging
import os
import ssl
import time

import aiohttp
from aiohttp import web

from . import appkeys, providers, tts_pending
from . import config as voice_config
from .engine import behavior, frames
from .providers import deepgram
from .providers.base import SttProvider, TtsError, TtsProvider
from .sections import settings_view, store_setting
from .settings import Domain, JsonValue

logger = logging.getLogger("voice")

# Pending TTS clips awaiting a streamed GET (see tts_pending / issue #466).
_PENDING_TTS: tts_pending.PendingStore = {}

# The audio format names of `/tts/speak`, and the play format each one is.
SPEAK_FORMATS: dict[str, str] = {"mp3": "mp3_22050", "pcm": "pcm_16000"}
# `/stt/listen` speaks the Deepgram wire format to its client, so it works with Deepgram only.
LISTEN_PROVIDER = "deepgram"

_VESTAD_PORT = os.environ.get("VESTAD_PORT", "")
_BOX_HOST = os.environ.get("BOX_HOST", "")
_AGENT_NAME = os.environ.get("AGENT_NAME", "")
_AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")


async def _notify_invalidation(scope: str) -> None:
    """Fire-and-forget POST to vestad to invalidate the voice service."""
    if not _VESTAD_PORT or not _BOX_HOST or not _AGENT_NAME:
        return
    url = f"https://{_BOX_HOST}:{_VESTAD_PORT}/agents/{_AGENT_NAME}/services/voice/invalidate"
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    headers = {}
    if _AGENT_TOKEN:
        headers["X-Agent-Token"] = _AGENT_TOKEN
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                url,
                json={"scope": scope},
                headers=headers,
                ssl=ssl_ctx,
                timeout=aiohttp.ClientTimeout(total=5),
            ),
        ):
            pass
    except Exception as exc:
        logger.debug("invalidation notify failed: %s", exc)


# Fire-and-forget invalidation tasks; the set keeps a strong reference until each completes.
_INVALIDATION_TASKS: set[asyncio.Task[None]] = set()


def _spawn_invalidation(scope: str) -> None:
    task = asyncio.create_task(_notify_invalidation(scope))
    _INVALIDATION_TASKS.add(task)
    task.add_done_callback(_INVALIDATION_TASKS.discard)


def _error(message: str, status: int) -> web.Response:
    return web.json_response({"error": message}, status=status)


def _role_entry(request: web.Request, role: voice_config.Role) -> tuple[Domain, str] | web.Response:
    """The role's entry and its selected provider name, or a 503 when it has none."""
    entry = voice_config.load(request.app[appkeys.DATA_DIR])[role]
    name = voice_config.provider_name(entry)
    if not entry or name is None:
        return _error(f"{role.upper()} not configured", 503)
    return entry, name


def _stt(request: web.Request) -> tuple[Domain, str, SttProvider] | web.Response:
    resolved = _role_entry(request, "stt")
    if isinstance(resolved, web.Response):
        return resolved
    entry, name = resolved
    provider = providers.get_stt(name)
    return (entry, name, provider) if provider is not None else _error(f"unknown stt provider: {name}", 500)


def _tts(request: web.Request) -> tuple[Domain, str, TtsProvider] | web.Response:
    resolved = _role_entry(request, "tts")
    if isinstance(resolved, web.Response):
        return resolved
    entry, name = resolved
    provider = providers.get_tts(name)
    return (entry, name, provider) if provider is not None else _error(f"unknown tts provider: {name}", 500)


async def _json_body(request: web.Request) -> dict[str, JsonValue] | web.Response:
    """Parse a JSON object body. Returns the object, or a 400 Response."""
    try:
        body = await request.json()
    except ValueError:
        return _error("invalid JSON body", 400)
    return body if isinstance(body, dict) else {}


def _status(entry: Domain | None, settings: list[dict[str, JsonValue]]) -> web.Response:
    name = voice_config.provider_name(entry)
    connected = voice_config.connected(entry)
    if not entry or name is None:
        return web.json_response({"configured": False, "provider": None, "connected": connected})
    return web.json_response(
        {"configured": True, "provider": name, "enabled": voice_config.is_enabled(entry), "connected": connected, "settings": settings}
    )


# --- STT ---


async def stt_status(request: web.Request) -> web.Response:
    """STT config (local read only, so it is instant)."""
    entry = voice_config.load(request.app[appkeys.DATA_DIR])["stt"]
    name = voice_config.provider_name(entry)
    provider = providers.get_stt(name) if name is not None else None
    return _status(entry, settings_view(provider.settings_schema(), entry) if entry and provider else [])


async def stt_usage(request: web.Request) -> web.Response:
    """STT provider usage/balance (hits external API)."""
    resolved = _stt(request)
    if isinstance(resolved, web.Response):
        return resolved
    entry, name, provider = resolved
    creds = voice_config.provider_creds(entry, name)
    out: dict[str, JsonValue] = {}
    usage, balance = await asyncio.gather(provider.usage(creds), provider.balance(creds), return_exceptions=True)
    if not isinstance(usage, BaseException):
        out["usage"] = usage
    if not isinstance(balance, BaseException):
        out["balance"] = balance
    return web.json_response(out)


async def _set_enabled(request: web.Request, role: voice_config.Role) -> web.Response:
    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    value = body["value"] if "value" in body else None
    if not isinstance(value, bool):
        return _error("value must be a boolean", 400)
    try:
        voice_config.set_enabled(request.app[appkeys.DATA_DIR], role, value)
    except ValueError as e:
        return _error(str(e), 400)
    _spawn_invalidation(role)
    return web.json_response({"ok": True})


async def stt_set_enabled(request: web.Request) -> web.Response:
    return await _set_enabled(request, "stt")


async def stt_set_eot(request: web.Request) -> web.Response:
    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    if "threshold" in body:
        return await _store_setting(request, "stt", "eot_threshold", body["threshold"])
    if "timeout_ms" in body:
        return await _store_setting(request, "stt", "eot_timeout_ms", body["timeout_ms"])
    return _error("threshold or timeout_ms required", 400)


async def stt_listen(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    entry = voice_config.load(request.app[appkeys.DATA_DIR])["stt"]
    if not entry or LISTEN_PROVIDER not in voice_config.connected(entry):
        await ws.close(code=1011, message=b"STT not configured")
        return ws
    await deepgram.relay(ws, voice_config.provider_creds(entry, LISTEN_PROVIDER), entry)
    return ws


# --- TTS ---


async def tts_status(request: web.Request) -> web.Response:
    """TTS config + voices (local read only, so it is instant)."""
    entry = voice_config.load(request.app[appkeys.DATA_DIR])["tts"]
    name = voice_config.provider_name(entry)
    provider = providers.get_tts(name) if name is not None else None
    if not entry or name is None or provider is None:
        return _status(entry, [])
    settings = settings_view(provider.settings_schema(), entry)
    for setting in settings:
        if setting["key"] == provider.voice_setting:
            # The voice select offers the provider's voices and the user's own, and it always
            # shows the voice that speaks.
            options = [*(setting["options"] if "options" in setting and isinstance(setting["options"], list) else [])]
            for voice in voice_config.custom_voices(entry):
                if "provider" in voice and voice["provider"] == name and "id" in voice:
                    option: dict[str, JsonValue] = {
                        "value": voice["id"],
                        "label": voice["name"] if "name" in voice else voice["id"],
                        "custom": True,
                    }
                    if "description" in voice:
                        option["description"] = voice["description"]
                    options.append(option)
            setting["options"] = options
            setting["value"] = providers.selected_voice(provider, entry)
    return _status(entry, settings)


async def tts_usage(request: web.Request) -> web.Response:
    """TTS provider usage (hits external API)."""
    resolved = _tts(request)
    if isinstance(resolved, web.Response):
        return resolved
    entry, name, provider = resolved
    return web.json_response({"usage": await provider.subscription(voice_config.provider_creds(entry, name))})


async def tts_set_enabled(request: web.Request) -> web.Response:
    return await _set_enabled(request, "tts")


async def tts_set_voice(request: web.Request) -> web.Response:
    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    voice_id = body["voice_id"].strip() if "voice_id" in body and isinstance(body["voice_id"], str) else ""
    if not voice_id:
        return _error("voice_id required", 400)
    resolved = _tts(request)
    if isinstance(resolved, web.Response):
        return resolved
    _entry, _name, provider = resolved
    response = await _store_setting(request, "tts", provider.voice_setting, voice_id)
    return web.json_response({"ok": True}) if response.status == 200 else response


# --- settings ---


async def _store_setting(request: web.Request, section: voice_config.Section, key: str, value: JsonValue) -> web.Response:
    if not isinstance(value, bool | int | float | str):
        return _error("value must be a boolean, a number, or text", 400)
    try:
        store_setting(request.app[appkeys.DATA_DIR], section, key, value)
    except ValueError as e:
        return _error(str(e), 400)
    _spawn_invalidation(section)
    # Return the full updated status so the client doesn't need a separate refresh.
    if section == "stt":
        return await stt_status(request)
    if section == "tts":
        return await tts_status(request)
    return await behavior_status(request)


async def set_setting(request: web.Request) -> web.Response:
    """Generic setter: checks the value, saves it, and returns the updated status."""
    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    key = body["key"] if "key" in body else None
    if not key or not isinstance(key, str):
        return _error("key required", 400)
    section = request.match_info["domain"]
    if section not in ("stt", "tts", "behavior"):
        return _error("domain must be stt, tts, or behavior", 400)
    return await _store_setting(request, section, key, body["value"] if "value" in body else None)


async def behavior_status(request: web.Request) -> web.Response:
    config = voice_config.load(request.app[appkeys.DATA_DIR])
    return web.json_response({"settings": settings_view(behavior.BEHAVIOR_SCHEMA, voice_config.behaviors(config))})


async def _use(request: web.Request, role: voice_config.Role) -> web.Response:
    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    provider = body["provider"] if "provider" in body else None
    if not provider or not isinstance(provider, str):
        return _error("provider required", 400)
    try:
        voice_config.use(request.app[appkeys.DATA_DIR], role, provider)
    except ValueError as e:
        return _error(str(e), 400)
    _spawn_invalidation(role)
    return await (stt_status(request) if role == "stt" else tts_status(request))


async def stt_use(request: web.Request) -> web.Response:
    return await _use(request, "stt")


async def tts_use(request: web.Request) -> web.Response:
    return await _use(request, "tts")


# --- TTS audio for the stock app ---


async def _speak_response(request: web.Request, text: str, speak_format: str) -> web.StreamResponse:
    resolved = _tts(request)
    if isinstance(resolved, web.Response):
        return resolved
    entry, name, provider = resolved
    if speak_format not in SPEAK_FORMATS or SPEAK_FORMATS[speak_format] not in provider.formats:
        return _error(f"unsupported audio format: {speak_format}", 400)
    play_format = SPEAK_FORMATS[speak_format]
    audio = provider.synthesize(
        text, providers.selected_voice(provider, entry), play_format, voice_config.provider_creds(entry, name), entry, request.app[appkeys.HTTP]
    )
    # Read the first audio before the headers go out, so a refused synthesis gets an error status.
    try:
        first = await anext(audio, b"")
    except TtsError as e:
        logger.error("tts synthesis failed: %s", e)
        return _error(str(e), 502)
    response = web.StreamResponse(status=200, headers={"Content-Type": frames.PLAY_FORMATS[play_format]})
    await response.prepare(request)
    await response.write(first)
    try:
        async for chunk in audio:
            await response.write(chunk)
    except TtsError as e:
        logger.error("tts synthesis failed mid-stream: %s", e)
    await response.write_eof()
    return response


def _text_of(body: dict[str, JsonValue]) -> str:
    return body["text"].strip() if "text" in body and isinstance(body["text"], str) else ""


async def tts_speak(request: web.Request) -> web.StreamResponse:
    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    text = _text_of(body)
    if not text:
        return _error("text required", 400)
    # "format" selects the audio encoding: "mp3" (default, the app's <audio> element) or "pcm"
    # (raw signed 16-bit LE mono at 16 kHz, which a phone-call consumer plays into a live call).
    speak_format = body["format"] if "format" in body and isinstance(body["format"], str) else "mp3"
    return await _speak_response(request, text, speak_format)


async def tts_prepare(request: web.Request) -> web.Response:
    """Register text and return a short-lived id the app streams via GET (issue #466)."""
    resolved = _tts(request)
    if isinstance(resolved, web.Response):
        return resolved
    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    text = _text_of(body)
    if not text:
        return _error("text required", 400)
    token = tts_pending.register(_PENDING_TTS, text, time.monotonic())
    return web.json_response({"id": token})


async def tts_stream(request: web.Request) -> web.StreamResponse:
    """Stream the audio for a prepared id so a native <audio> element can play it."""
    text = tts_pending.resolve(_PENDING_TTS, request.match_info["id"], time.monotonic())
    if text is None:
        return _error("unknown or expired tts id", 404)
    return await _speak_response(request, text, "mp3")
