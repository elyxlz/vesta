"""Voice skill entrypoint.

Auto-loaded by the agent at startup. The skill is mounted at /voice/ on
the container's aiohttp server, so /status here becomes /voice/status
and /agents/{name}/api/voice/status through vestad.
"""

import asyncio
import typing as tp

from aiohttp import web

from vesta import logger

from . import config as voice_config
from . import providers


def routes() -> list[web.RouteDef]:
    return [
        web.get("/status", _status_handler),
        web.get("/tts/voices", _voices_handler),
        web.post("/tts/speak", _speak_handler),
        web.get("/stt/listen", _listen_handler),
    ]


def _data_dir(request: web.Request) -> tp.Any:
    return request.app["config"].data_dir


async def _status_handler(request: web.Request) -> web.Response:
    cfg = voice_config.load(_data_dir(request))
    stt_entry = cfg.get("stt")
    tts_entry = cfg.get("tts")

    stt_out: dict = {"configured": False, "provider": None}
    if stt_entry and stt_entry.get("provider"):
        provider_name = stt_entry["provider"]
        stt_out = {
            "configured": True,
            "provider": provider_name,
            "eot_threshold": stt_entry.get("eot_threshold", 0.8),
            "eot_timeout_ms": stt_entry.get("eot_timeout_ms", 10000),
            "keyterms": stt_entry.get("keyterms", []),
        }
        provider = providers.get_stt(provider_name)
        if provider:
            creds = (stt_entry.get("credentials") or {}).get(provider_name) or {}
            usage_task = provider.usage(creds)
            balance_task = provider.balance(creds)
            usage, balance = await asyncio.gather(usage_task, balance_task, return_exceptions=True)
            if not isinstance(usage, BaseException):
                stt_out["usage"] = usage
            if not isinstance(balance, BaseException):
                stt_out["balance"] = balance

    tts_out: dict = {"configured": False, "provider": None}
    if tts_entry and tts_entry.get("provider"):
        provider_name = tts_entry["provider"]
        tts_out = {
            "configured": True,
            "provider": provider_name,
            "selected_voice_id": tts_entry.get("selected_voice_id"),
        }
        provider = providers.get_tts(provider_name)
        if provider:
            creds = (tts_entry.get("credentials") or {}).get(provider_name) or {}
            try:
                sub = await provider.subscription(creds)
                tts_out["usage"] = sub
            except Exception as e:
                logger.error(f"tts subscription fetch failed: {e}")

    return web.json_response({"stt": stt_out, "tts": tts_out})


async def _voices_handler(request: web.Request) -> web.Response:
    cfg = voice_config.load(_data_dir(request))
    tts_entry = cfg.get("tts")
    if not tts_entry or not tts_entry.get("provider"):
        return web.json_response({"error": "TTS not configured"}, status=503)
    provider_name = tts_entry["provider"]
    provider = providers.get_tts(provider_name)
    if not provider:
        return web.json_response({"error": f"unknown tts provider: {provider_name}"}, status=500)

    voices = provider.premade_voices()
    custom = tts_entry.get("custom_voices") or []
    for v in custom:
        if v.get("provider") == provider_name:
            voices.append({"id": v["id"], "name": v["name"], "custom": True})

    selected = tts_entry.get("selected_voice_id")
    if selected and not any(v["id"] == selected for v in voices) and voices:
        selected = voices[0]["id"]
    elif not selected and voices:
        selected = voices[0]["id"]

    return web.json_response({
        "provider": provider_name,
        "selected_voice_id": selected,
        "voices": voices,
    })


async def _speak_handler(request: web.Request) -> web.StreamResponse:
    cfg = voice_config.load(_data_dir(request))
    tts_entry = cfg.get("tts")
    if not tts_entry or not tts_entry.get("provider"):
        return web.json_response({"error": "TTS not configured"}, status=503)
    provider_name = tts_entry["provider"]
    provider = providers.get_tts(provider_name)
    if not provider:
        return web.json_response({"error": f"unknown tts provider: {provider_name}"}, status=500)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    text = (body or {}).get("text", "").strip()
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


async def _listen_handler(request: web.Request) -> web.WebSocketResponse:
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
