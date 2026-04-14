import asyncio
import logging
import os
import pathlib as pl
import ssl
import typing as tp

import aiohttp
from aiohttp import web

from . import config as voice_config
from . import providers

logger = logging.getLogger("voice")

DATA_DIR = pl.Path.home() / ".voice"

_VESTAD_PORT = os.environ.get("VESTAD_PORT", "")
_AGENT_NAME = os.environ.get("AGENT_NAME", "")
_AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")


async def _notify_invalidation(scope: str) -> None:
    """Fire-and-forget POST to vestad to invalidate the voice service."""
    if not _VESTAD_PORT or not _AGENT_NAME:
        return
    url = f"https://localhost:{_VESTAD_PORT}/agents/{_AGENT_NAME}/services/voice/invalidate"
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    headers = {}
    if _AGENT_TOKEN:
        headers["X-Agent-Token"] = _AGENT_TOKEN
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"scope": scope},
                headers=headers,
                ssl=ssl_ctx,
                timeout=aiohttp.ClientTimeout(total=5),
            ):
                pass
    except Exception as exc:
        logger.debug("invalidation notify failed: %s", exc)


def _resolve_domain(
    domain: tp.Literal["stt", "tts"],
) -> tuple[dict, str, tp.Any, dict[str, str]] | web.Response:
    """Load config and resolve provider + creds for a domain.

    Returns (entry, provider_name, provider, creds) or a 503/500 Response.
    """
    cfg = voice_config.load(DATA_DIR)
    entry = cfg.get(domain)
    if not entry or not entry.get("provider"):
        return web.json_response({"error": f"{domain.upper()} not configured"}, status=503)
    provider_name = entry["provider"]
    getter = providers.get_stt if domain == "stt" else providers.get_tts
    provider = getter(provider_name)
    if not provider:
        return web.json_response({"error": f"unknown {domain} provider: {provider_name}"}, status=500)
    creds = (entry.get("credentials") or {}).get(provider_name) or {}
    return entry, provider_name, provider, creds


async def _json_body(request: web.Request) -> dict | web.Response:
    """Parse JSON body. Returns dict on success, or a 400 Response on failure."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    return body or {}


# --- STT ---


def _merge_setting_values(setting: dict, entry: dict) -> dict:
    merged = dict(setting)
    merged["value"] = entry.get(merged["key"], merged.get("default"))
    raw_config = merged.get("config")
    if isinstance(raw_config, list):
        merged["config"] = [_merge_setting_values(dict(ch), entry) for ch in raw_config]
    return merged


def _build_settings(provider: tp.Any, entry: tp.Any) -> list[dict]:
    """Merge provider schema with current config values."""
    if not hasattr(provider, "settings_schema"):
        return []
    return [_merge_setting_values(dict(s), entry) for s in provider.settings_schema()]


async def stt_status(request: web.Request) -> web.Response:
    """STT config (local read only — instant)."""
    cfg = voice_config.load(DATA_DIR)
    stt_entry = cfg.get("stt")

    if not stt_entry or not stt_entry.get("provider"):
        return web.json_response({"configured": False, "provider": None})

    provider_name = stt_entry["provider"]
    provider = providers.get_stt(provider_name)
    settings = _build_settings(provider, stt_entry) if provider else []

    return web.json_response(
        {
            "configured": True,
            "provider": provider_name,
            "enabled": stt_entry.get("enabled", False),
            "settings": settings,
        }
    )


async def stt_usage(request: web.Request) -> web.Response:
    """STT provider usage/balance (hits external API)."""
    resolved = _resolve_domain("stt")
    if isinstance(resolved, web.Response):
        return resolved
    _entry, _name, provider, creds = resolved
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
    setter(DATA_DIR, value)
    return web.json_response({"ok": True})


async def stt_set_enabled(request: web.Request) -> web.Response:
    resp = await _set_bool(request, lambda d, v: voice_config.set_enabled(d, "stt", v))
    if resp.status == 200:
        asyncio.create_task(_notify_invalidation("stt"))
    return resp


async def stt_set_auto_send(request: web.Request) -> web.Response:
    resp = await _set_bool(request, voice_config.set_stt_auto_send)
    if resp.status == 200:
        asyncio.create_task(_notify_invalidation("stt"))
    return resp


async def stt_set_eot(request: web.Request) -> web.Response:
    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    try:
        if "threshold" in body:
            voice_config.set_eot_threshold(DATA_DIR, float(body["threshold"]))
        elif "timeout_ms" in body:
            voice_config.set_eot_timeout_ms(DATA_DIR, int(body["timeout_ms"]))
        else:
            return web.json_response({"error": "threshold or timeout_ms required"}, status=400)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    asyncio.create_task(_notify_invalidation("stt"))
    return web.json_response({"ok": True})


async def stt_listen(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    resolved = _resolve_domain("stt")
    if isinstance(resolved, web.Response):
        await ws.prepare(request)
        await ws.close(code=1011, message=b"STT not configured")
        return ws
    entry, _name, provider, creds = resolved
    await ws.prepare(request)
    await provider.relay(ws, creds, dict(entry))
    return ws


# --- TTS ---


async def tts_status(request: web.Request) -> web.Response:
    """TTS config + voices (local read only — instant)."""
    cfg = voice_config.load(DATA_DIR)
    tts_entry = cfg.get("tts")

    if not tts_entry or not tts_entry.get("provider"):
        return web.json_response({"configured": False, "provider": None})

    provider_name = tts_entry["provider"]
    provider = providers.get_tts(provider_name)
    settings = _build_settings(provider, tts_entry) if provider else []

    # Merge custom voices into the select options for voice selection settings
    custom = tts_entry.get("custom_voices") or []
    for setting in settings:
        if setting.get("type") == "select" and setting["key"] == "selected_voice_id":
            options = list(setting.get("options") or [])
            for v in custom:
                if v.get("provider") == provider_name:
                    entry: dict = {"value": v["id"], "label": v["name"], "custom": True}
                    if v.get("description"):
                        entry["description"] = v["description"]
                    options.append(entry)
            setting["options"] = options
            # Auto-select first voice if none selected
            selected = setting.get("value")
            if options and (not selected or not any(o["value"] == selected for o in options)):
                setting["value"] = options[0]["value"]

    return web.json_response(
        {
            "configured": True,
            "provider": provider_name,
            "enabled": tts_entry.get("enabled", False),
            "settings": settings,
        }
    )


async def tts_usage(request: web.Request) -> web.Response:
    """TTS provider usage (hits external API)."""
    resolved = _resolve_domain("tts")
    if isinstance(resolved, web.Response):
        return resolved
    _entry, _name, provider, creds = resolved
    try:
        sub = await provider.subscription(creds)
        return web.json_response({"usage": sub})
    except Exception as e:
        logger.error(f"tts usage fetch failed: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def tts_set_enabled(request: web.Request) -> web.Response:
    resp = await _set_bool(request, lambda d, v: voice_config.set_enabled(d, "tts", v))
    if resp.status == 200:
        asyncio.create_task(_notify_invalidation("tts"))
    return resp


async def tts_set_voice(request: web.Request) -> web.Response:
    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    voice_id = body.get("voice_id", "").strip()
    if not voice_id:
        return web.json_response({"error": "voice_id required"}, status=400)
    try:
        voice_config.set_voice(DATA_DIR, voice_id)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    asyncio.create_task(_notify_invalidation("tts"))
    return web.json_response({"ok": True})


async def set_setting(request: web.Request) -> web.Response:
    """Generic setter — saves value and returns the updated domain status."""
    domain = request.match_info["domain"]
    if domain not in ("stt", "tts"):
        return web.json_response({"error": "domain must be stt or tts"}, status=400)
    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    key = body.get("key")
    value = body.get("value")
    if not key or not isinstance(key, str):
        return web.json_response({"error": "key required"}, status=400)
    try:
        voice_config.set_setting(DATA_DIR, domain, key, value)  # type: ignore[arg-type]
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    asyncio.create_task(_notify_invalidation(domain))
    # Return the full updated status so the client doesn't need a separate refresh.
    if domain == "stt":
        return await stt_status(request)
    return await tts_status(request)


async def tts_speak(request: web.Request) -> web.StreamResponse:
    resolved = _resolve_domain("tts")
    if isinstance(resolved, web.Response):
        return resolved
    entry, _name, provider, creds = resolved

    body = await _json_body(request)
    if isinstance(body, web.Response):
        return body
    text = body.get("text", "").strip()
    if not text:
        return web.json_response({"error": "text required"}, status=400)

    voice_id = entry.get("selected_voice_id")
    if not voice_id:
        voices = provider.premade_voices()
        voice_id = voices[0]["id"] if voices else None
    if not voice_id:
        return web.json_response({"error": "no voice selected"}, status=500)

    return await provider.speak(text, voice_id, creds, request)
