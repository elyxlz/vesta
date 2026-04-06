import asyncio
import logging
import os
import pathlib as pl
import typing as tp

from aiohttp import web

from . import config as voice_config
from . import providers

logger = logging.getLogger("voice")


def _data_dir(request: web.Request) -> pl.Path:
    return pl.Path(os.environ["VESTA_DATA_DIR"])



async def _json_body(request: web.Request) -> dict | web.Response:
    """Parse JSON body. Returns dict on success, or a 400 Response on failure."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    return body or {}


# --- STT ---


async def stt_status(request: web.Request) -> web.Response:
    """STT config (local read only — instant)."""
    cfg = voice_config.load(_data_dir(request))
    stt_entry = cfg.get("stt")

    if not stt_entry or not stt_entry.get("provider"):
        return web.json_response({"configured": False, "provider": None})

    return web.json_response({
        "configured": True,
        "provider": stt_entry["provider"],
        "enabled": stt_entry.get("enabled", True),
        "auto_send": stt_entry.get("auto_send", True),
        "eot_threshold": stt_entry.get("eot_threshold", 0.8),
        "eot_timeout_ms": stt_entry.get("eot_timeout_ms", 10000),
        "keyterms": stt_entry.get("keyterms", []),
    })


async def stt_usage(request: web.Request) -> web.Response:
    """STT provider usage/balance (hits external API)."""
    cfg = voice_config.load(_data_dir(request))
    stt_entry = cfg.get("stt")
    if not stt_entry or not stt_entry.get("provider"):
        return web.json_response({"error": "STT not configured"}, status=503)
    provider_name = stt_entry["provider"]
    provider = providers.get_stt(provider_name)
    if not provider:
        return web.json_response({"error": f"unknown stt provider: {provider_name}"}, status=500)
    creds = (stt_entry.get("credentials") or {}).get(provider_name) or {}
    out: dict = {}
    usage, balance = await asyncio.gather(provider.usage(creds), provider.balance(creds), return_exceptions=True)
    if not isinstance(usage, BaseException):
        out["usage"] = usage
    if not isinstance(balance, BaseException):
        out["balance"] = balance
    return web.json_response(out)


async def _set_bool(request: web.Request, setter: tp.Callable[..., tp.Any]) -> web.Response:
    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    value = body.get("value")
    if not isinstance(value, bool):
        return web.json_response({"error": "value must be a boolean"}, status=400)
    setter(_data_dir(request), value)
    return web.json_response({"ok": True})


async def stt_set_enabled(request: web.Request) -> web.Response:
    return await _set_bool(request, lambda d, v: voice_config.set_enabled(d, "stt", v))


async def stt_set_auto_send(request: web.Request) -> web.Response:
    return await _set_bool(request, voice_config.set_stt_auto_send)


async def stt_set_eot(request: web.Request) -> web.Response:
    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    try:
        if "threshold" in body:
            voice_config.set_eot_threshold(_data_dir(request), float(body["threshold"]))
        elif "timeout_ms" in body:
            voice_config.set_eot_timeout_ms(_data_dir(request), int(body["timeout_ms"]))
        else:
            return web.json_response({"error": "threshold or timeout_ms required"}, status=400)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"ok": True})


async def stt_listen(request: web.Request) -> web.WebSocketResponse:
    cfg = voice_config.load(_data_dir(request))
    stt_entry = cfg.get("stt")
    ws = web.WebSocketResponse()
    if not stt_entry or not stt_entry.get("provider"):
        await ws.prepare(request)
        await ws.close(code=1011, message=b"STT not configured")
        return ws
    provider_name = stt_entry["provider"]
    provider = providers.get_stt(provider_name)
    if not provider:
        await ws.prepare(request)
        await ws.close(code=1011, message=f"unknown stt provider: {provider_name}".encode())
        return ws

    creds = (stt_entry.get("credentials") or {}).get(provider_name) or {}
    await ws.prepare(request)
    await provider.relay(ws, creds, dict(stt_entry))
    return ws


# --- TTS ---


async def tts_status(request: web.Request) -> web.Response:
    """TTS config + voices (local read only — instant)."""
    cfg = voice_config.load(_data_dir(request))
    tts_entry = cfg.get("tts")

    if not tts_entry or not tts_entry.get("provider"):
        return web.json_response({"configured": False, "provider": None})

    provider_name = tts_entry["provider"]
    provider = providers.get_tts(provider_name)
    voice_list: list[dict] = []
    selected = tts_entry.get("selected_voice_id")
    if provider:
        voice_list = provider.premade_voices()
        custom = tts_entry.get("custom_voices") or []
        for v in custom:
            if v.get("provider") == provider_name:
                voice_list.append({"id": v["id"], "name": v["name"], "custom": True})
        if selected and not any(v["id"] == selected for v in voice_list) and voice_list:
            selected = voice_list[0]["id"]
        elif not selected and voice_list:
            selected = voice_list[0]["id"]

    return web.json_response({
        "configured": True,
        "provider": provider_name,
        "enabled": tts_entry.get("enabled", False),
        "selected_voice_id": selected,
        "voices": voice_list,
    })


async def tts_usage(request: web.Request) -> web.Response:
    """TTS provider usage (hits external API)."""
    cfg = voice_config.load(_data_dir(request))
    tts_entry = cfg.get("tts")
    if not tts_entry or not tts_entry.get("provider"):
        return web.json_response({"error": "TTS not configured"}, status=503)
    provider_name = tts_entry["provider"]
    provider = providers.get_tts(provider_name)
    if not provider:
        return web.json_response({"error": f"unknown tts provider: {provider_name}"}, status=500)
    creds = (tts_entry.get("credentials") or {}).get(provider_name) or {}
    try:
        sub = await provider.subscription(creds)
        return web.json_response({"usage": sub})
    except Exception as e:
        logger.error(f"tts usage fetch failed: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def tts_set_enabled(request: web.Request) -> web.Response:
    return await _set_bool(request, lambda d, v: voice_config.set_enabled(d, "tts", v))


async def tts_set_voice(request: web.Request) -> web.Response:
    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    voice_id = body.get("voice_id", "").strip()
    if not voice_id:
        return web.json_response({"error": "voice_id required"}, status=400)
    try:
        voice_config.set_voice(_data_dir(request), voice_id)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"ok": True})


async def tts_speak(request: web.Request) -> web.StreamResponse:
    cfg = voice_config.load(_data_dir(request))
    tts_entry = cfg.get("tts")
    if not tts_entry or not tts_entry.get("provider"):
        return web.json_response({"error": "TTS not configured"}, status=503)
    provider_name = tts_entry["provider"]
    provider = providers.get_tts(provider_name)
    if not provider:
        return web.json_response({"error": f"unknown tts provider: {provider_name}"}, status=500)

    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    text = body.get("text", "").strip()
    if not text:
        return web.json_response({"error": "text required"}, status=400)

    voice_id = tts_entry.get("selected_voice_id")
    if not voice_id:
        voices = provider.premade_voices()
        voice_id = voices[0]["id"] if voices else None
    if not voice_id:
        return web.json_response({"error": "no voice selected"}, status=500)

    creds = (tts_entry.get("credentials") or {}).get(provider_name) or {}
    return await provider.speak(text, voice_id, creds, request)
