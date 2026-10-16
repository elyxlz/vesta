"""The HTTP routes of the voice service: status, settings, and the audio routes with no session.

A voice session is the engine socket (engine/session.py). The `/tts/` audio routes make the
audio of one text with no session: the stock app reads a reply aloud through them when no
session is open. `/stt/listen` (listen.py) serves older builds of the app.
"""

import asyncio
import logging
import time

from aiohttp import web

from . import appkeys, invalidation, listen, providers, sections, tts_pending
from . import config as voice_config
from .engine import frames
from .providers.base import SttOpenError, TtsError, Usage
from .settings import Domain, JsonValue

logger = logging.getLogger("voice")

# Pending TTS clips awaiting a streamed GET (see tts_pending / issue #466).
_PENDING_TTS: tts_pending.PendingStore = {}

# The audio format names of `/tts/speak`, and the play format each one is.
SPEAK_FORMATS: dict[str, str] = {"mp3": "mp3_22050", "pcm": "pcm_16000"}
# A WebSocket close reason holds 123 bytes at most.
CLOSE_REASON_MAX_BYTES = 123

# Fire-and-forget invalidation tasks; the set keeps a strong reference until each completes.
_INVALIDATION_TASKS: set[asyncio.Task[None]] = set()


def _spawn_invalidation(scope: str) -> None:
    task = asyncio.create_task(invalidation.notify(scope))
    _INVALIDATION_TASKS.add(task)
    task.add_done_callback(_INVALIDATION_TASKS.discard)


def _error(message: str, status: int) -> web.Response:
    return web.json_response({"error": message}, status=status)


def _load(request: web.Request) -> voice_config.VoiceConfig:
    return voice_config.load(request.app[appkeys.DATA_DIR])


def _role(request: web.Request) -> voice_config.Role:
    """The role a `/{role}/...` route names. The route pattern admits only a role."""
    return next(role for role in voice_config.ROLES if role == request.match_info["role"])


def _selected[P](request: web.Request, role: voice_config.Role, registry: dict[str, P]) -> tuple[Domain, str, P] | web.Response:
    """The role's entry, its selected provider name, and that provider, or the error to answer."""
    entry = _load(request)[role]
    name = voice_config.provider_name(entry)
    if name is None:
        return _error(f"{role.upper()} not configured", 503)
    if name not in registry:
        return _error(f"unknown {role} provider: {name}", 500)
    return entry, name, registry[name]


async def _json_body(request: web.Request) -> dict[str, JsonValue] | web.Response:
    """Parse a JSON object body. Returns the object, or a 400 Response."""
    try:
        body = await request.json()
    except ValueError:
        return _error("invalid JSON body", 400)
    return body if isinstance(body, dict) else {}


# --- status and settings ---


def _role_status(config: voice_config.VoiceConfig, role: voice_config.Role) -> web.Response:
    entry = config[role]
    name = voice_config.provider_name(entry)
    connected = voice_config.connected(entry)
    if name is None:
        return web.json_response({"configured": False, "provider": None, "connected": connected})
    status = {"configured": True, "provider": name, "enabled": voice_config.is_enabled(entry), "connected": connected}
    return web.json_response({**status, "settings": sections.section_view(config, role)})


def _section_status(request: web.Request, section: voice_config.Section) -> web.Response:
    config = _load(request)
    if section == "behavior":
        return web.json_response({"settings": sections.section_view(config, "behavior")})
    return _role_status(config, section)


async def role_status(request: web.Request) -> web.Response:
    """The config of one role and the settings of its selected provider (local read only, so it is instant)."""
    return _role_status(_load(request), _role(request))


async def behavior_status(request: web.Request) -> web.Response:
    return _section_status(request, "behavior")


async def set_enabled(request: web.Request) -> web.Response:
    role = _role(request)
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


async def use(request: web.Request) -> web.Response:
    """Select a connected provider of the role, and return the updated status."""
    role = _role(request)
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
    return _section_status(request, role)


async def _store_setting(request: web.Request, section: voice_config.Section, key: str, value: JsonValue) -> web.Response:
    if not isinstance(value, bool | int | float | str):
        return _error("value must be a boolean, a number, or text", 400)
    try:
        sections.store_setting(request.app[appkeys.DATA_DIR], section, key, value)
    except ValueError as e:
        return _error(str(e), 400)
    _spawn_invalidation(section)
    # Return the full updated status so the client doesn't need a separate refresh.
    return _section_status(request, section)


async def set_setting(request: web.Request) -> web.Response:
    """Generic setter: checks the value, saves it, and returns the updated status."""
    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    key = body["key"] if "key" in body else None
    if not key or not isinstance(key, str):
        return _error("key required", 400)
    section = next(name for name in voice_config.SECTIONS if name == request.match_info["domain"])
    return await _store_setting(request, section, key, body["value"] if "value" in body else None)


# --- STT ---


async def stt_usage(request: web.Request) -> web.Response:
    """What the account of the STT provider used and has left (asks the provider's API)."""
    resolved = _selected(request, "stt", providers.STT)
    if isinstance(resolved, web.Response):
        return resolved
    entry, name, provider = resolved
    usage = await provider.usage(voice_config.provider_creds(entry, name))
    return web.json_response({**usage, **_legacy_stt_usage(usage)})


# LEGACY(remove-when: MIN_SUPPORTED_CLIENT_VERSION in vestad is 0.3.18 or higher): app builds
# older than 0.3.18 read the usage of each role in the shape of its first vendor, so both
# routes add that shape beside `used` and `left`.
def _legacy_stt_usage(usage: Usage) -> dict[str, JsonValue]:
    used, left = usage["used"], usage["left"]
    if used is None or left is None or used["unit"] != "hours":
        return {}
    return {
        "usage": {"results": [{"hours": used["amount"]}]},
        "balance": {"balances": [{"amount": left["amount"], "units": left["unit"]}]},
    }


def _legacy_tts_usage(usage: Usage) -> dict[str, JsonValue]:
    used, left = usage["used"], usage["left"]
    if left is None:
        return {}
    if used is not None and used["unit"] == left["unit"] == "credits":
        return {"usage": {"character_count": used["amount"], "character_limit": used["amount"] + left["amount"]}}
    return {"usage": {"balances": [{"amount": left["amount"], "units": left["unit"]}]}}


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
    resolved = _selected(request, "stt", providers.STT)
    if isinstance(resolved, web.Response) or not voice_config.is_enabled(resolved[0]):
        await ws.close(code=1011, message=b"STT not configured")
        return ws
    entry, name, provider = resolved
    try:
        stream = await provider.open(voice_config.provider_creds(entry, name), voice_config.provider_settings(entry))
    except SttOpenError as e:
        logger.warning("stt open failed for the listen socket (%s): %s", name, e)
        await ws.close(code=1011, message=str(e).encode()[:CLOSE_REASON_MAX_BYTES])
        return ws
    await listen.relay(ws, stream)
    return ws


# --- TTS ---


async def tts_usage(request: web.Request) -> web.Response:
    """What the account of the TTS provider used and has left (asks the provider's API)."""
    resolved = _selected(request, "tts", providers.TTS)
    if isinstance(resolved, web.Response):
        return resolved
    entry, name, provider = resolved
    usage = await provider.usage(voice_config.provider_creds(entry, name))
    return web.json_response({**usage, **_legacy_tts_usage(usage)})


async def tts_reply_hint(request: web.Request) -> web.Response:
    """What the agent must know to write a reply that this box can speak: the hint of the
    selected TTS provider while the role is on, and empty text in every other case."""
    entry = _load(request)["tts"]
    provider = providers.get_tts(voice_config.provider_name(entry))
    hint = provider.reply_hint if provider is not None and voice_config.is_enabled(entry) else ""
    return web.json_response({"reply_hint": hint})


async def tts_set_voice(request: web.Request) -> web.Response:
    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    voice_id = body["voice_id"].strip() if "voice_id" in body and isinstance(body["voice_id"], str) else ""
    if not voice_id:
        return _error("voice_id required", 400)
    try:
        sections.store_voice(request.app[appkeys.DATA_DIR], voice_id)
    except ValueError as e:
        return _error(str(e), 400)
    _spawn_invalidation("tts")
    return web.json_response({"ok": True})


async def _speak_response(request: web.Request, text: str, speak_format: str) -> web.StreamResponse:
    resolved = _selected(request, "tts", providers.TTS)
    if isinstance(resolved, web.Response):
        return resolved
    entry, name, provider = resolved
    if speak_format not in SPEAK_FORMATS or SPEAK_FORMATS[speak_format] not in provider.formats:
        return _error(f"unsupported audio format: {speak_format}", 400)
    play_format = SPEAK_FORMATS[speak_format]
    audio = provider.synthesize(
        text,
        providers.selected_voice(provider, entry),
        play_format,
        voice_config.provider_creds(entry, name),
        voice_config.provider_settings(entry),
        request.app[appkeys.HTTP],
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
    resolved = _selected(request, "tts", providers.TTS)
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
