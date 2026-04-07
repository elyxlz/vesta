"""Deepgram STT provider — Flux v2 realtime streaming."""

import asyncio
import logging
import typing as tp
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

logger = logging.getLogger("voice.deepgram")

DEEPGRAM_API = "https://api.deepgram.com"
DEEPGRAM_WS = "wss://api.deepgram.com"
MODEL = "flux-general-en"
ENCODING = "linear16"
SAMPLE_RATE = 16000


class DeepgramStt:
    name = "deepgram"

    def settings_schema(self) -> list[dict]:
        return [
            {
                "key": "auto_send",
                "type": "bool",
                "label": "auto-send on pause",
                "description": "send message automatically when you stop speaking",
                "default": True,
            },
            {
                "key": "eot_threshold",
                "type": "number",
                "label": "end-of-turn sensitivity",
                "description": "lower finalizes turns faster; higher waits longer",
                "default": 0.8,
                "min": 0.3,
                "max": 0.95,
                "step": 0.05,
            },
            {
                "key": "eot_timeout_ms",
                "type": "number",
                "label": "max silence timeout",
                "description": "max silence before forcing end of turn",
                "default": 10000,
                "min": 2000,
                "max": 15000,
                "step": 500,
                "unit": "ms",
            },
        ]

    def __init__(self) -> None:
        # Cache project_id per api_key so status checks don't hit /v1/projects
        # twice per request (usage + balance both need it).
        self._project_id_cache: dict[str, str] = {}

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

        from .. import config as voice_config

        keyterms: list[str] = stt_domain.get("keyterms") or []
        eot_threshold = stt_domain.get("eot_threshold", voice_config.DEFAULT_EOT_THRESHOLD)
        eot_timeout_ms = stt_domain.get("eot_timeout_ms", voice_config.DEFAULT_EOT_TIMEOUT_MS)

        params: list[tuple[str, str]] = [
            ("model", MODEL),
            ("encoding", ENCODING),
            ("sample_rate", str(SAMPLE_RATE)),
            ("eot_threshold", str(eot_threshold)),
            ("eot_timeout_ms", str(eot_timeout_ms)),
        ]
        for term in keyterms:
            params.append(("keyterm", term))

        url = f"{DEEPGRAM_WS}/v2/listen?{urlencode(params)}"
        headers = {"Authorization": f"Token {api_key}"}

        session = aiohttp.ClientSession()
        try:
            try:
                dg_ws = await session.ws_connect(url, headers=headers, heartbeat=30.0)
            except (TimeoutError, aiohttp.ClientError) as e:
                logger.error(f"deepgram connect failed: {e}")
                await browser_ws.close(code=1011, message=f"deepgram connect failed: {e}".encode())
                return

            async def browser_to_deepgram() -> None:
                async for msg in browser_ws:
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        await dg_ws.send_bytes(msg.data)
                    elif msg.type == aiohttp.WSMsgType.TEXT:
                        await dg_ws.send_str(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
                        break

            async def deepgram_to_browser() -> None:
                async for msg in dg_ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await browser_ws.send_str(msg.data)
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        await browser_ws.send_bytes(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
                        break

            tasks = [
                asyncio.create_task(browser_to_deepgram()),
                asyncio.create_task(deepgram_to_browser()),
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

    async def _cached_project_id(self, api_key: str) -> str | None:
        if (cached := self._project_id_cache.get(api_key)) is not None:
            return cached
        project_id = await _project_id(api_key)
        if project_id:
            self._project_id_cache[api_key] = project_id
        return project_id

    async def usage(self, creds: dict[str, str]) -> dict:
        api_key = creds.get("api_key", "")
        project_id = await self._cached_project_id(api_key)
        if not project_id:
            return {"error": "no project"}
        url = f"{DEEPGRAM_API}/v1/projects/{project_id}/usage/breakdown?endpoint=listen"
        return await _get_json(url, {"Authorization": f"Token {api_key}"})

    async def balance(self, creds: dict[str, str]) -> dict:
        api_key = creds.get("api_key", "")
        project_id = await self._cached_project_id(api_key)
        if not project_id:
            return {"error": "no project"}
        url = f"{DEEPGRAM_API}/v1/projects/{project_id}/balances"
        return await _get_json(url, {"Authorization": f"Token {api_key}"})

    async def validate(self, api_key: str) -> tuple[bool, str | None]:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{DEEPGRAM_API}/v1/projects",
                headers={"Authorization": f"Token {api_key}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 401:
                    return False, "invalid api key"
                if resp.status != 200:
                    return False, f"deepgram returned {resp.status}"
                body = await resp.json()
                if not body.get("projects"):
                    return False, "no projects on this account"
        return True, None


async def _project_id(api_key: str) -> str | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{DEEPGRAM_API}/v1/projects",
                headers={"Authorization": f"Token {api_key}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                body = await resp.json()
                projects = body.get("projects") or []
                if not projects:
                    return None
                return projects[0].get("project_id")
    except (TimeoutError, aiohttp.ClientError):
        return None


async def _get_json(url: str, headers: dict[str, str]) -> dict:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                body: tp.Any = await resp.json()
                if resp.status != 200:
                    return {"error": f"status {resp.status}", "body": body}
                return body
    except (TimeoutError, aiohttp.ClientError) as e:
        return {"error": str(e)}
