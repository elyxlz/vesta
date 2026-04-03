"""WebSocket API server for agent <-> app communication."""

import asyncio
import base64
import json
import os
import tempfile

from aiohttp import web

import vesta.models as vm
from vesta import logger
from vesta.events import EventBus, HistoryEvent, UserEvent, VestaEvent


async def _ws_handler(request: web.Request) -> web.WebSocketResponse:
    event_bus: EventBus = request.app["event_bus"]
    message_queue: asyncio.Queue[tuple[str, bool, bool]] = request.app["message_queue"]
    state: vm.State = request.app["state"]
    config: vm.VestaConfig = request.app["config"]

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    sub = event_bus.subscribe()
    recv_task: asyncio.Task[None] | None = None
    send_task: asyncio.Task[None] | None = None
    try:
        if event_bus.history:
            await ws.send_json(HistoryEvent(type="history", events=list(event_bus.history), state=event_bus.state))
        recv_task = asyncio.create_task(_recv_loop(ws, message_queue, state, config))
        send_task = asyncio.create_task(_send_loop(ws, sub))
        await asyncio.wait([recv_task, send_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        recv_task and recv_task.cancel()
        send_task and send_task.cancel()
        await asyncio.gather(recv_task, send_task, return_exceptions=True)
        event_bus.unsubscribe(sub)

    return ws


async def _recv_loop(
    ws: web.WebSocketResponse,
    message_queue: asyncio.Queue[tuple[str, bool, bool]],
    state: vm.State,
    config: vm.VestaConfig,
) -> None:
    async for msg in ws:
        if msg.type == web.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"WS bad message: {e}")
                continue
            try:
                msg_type = data["type"]
            except KeyError:
                continue
            if msg_type == "message":
                text = data["text"].strip()
                if text:
                    await message_queue.put((text, True, False))
            elif msg_type == "audio":
                audio_b64 = data.get("data", "")
                mime = data.get("mime", "audio/webm")
                if audio_b64:
                    asyncio.create_task(_handle_audio(audio_b64, mime, message_queue, state.event_bus))
            elif msg_type == "interrupt":
                from vesta.core.client import attempt_interrupt

                await attempt_interrupt(state, config=config, reason="WS interrupt")
        elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
            break


async def _handle_audio(
    audio_b64: str,
    mime: str,
    message_queue: asyncio.Queue[tuple[str, bool, bool]],
    event_bus: EventBus,
) -> None:
    """Decode base64 audio, transcribe it, and enqueue as a text message."""
    ext = ".webm"
    if "ogg" in mime:
        ext = ".ogg"
    elif "mp4" in mime:
        ext = ".m4a"

    tmp_path = ""
    try:
        audio_bytes = base64.b64decode(audio_b64)
        fd, tmp_path = tempfile.mkstemp(suffix=ext, prefix="ws_audio_")
        os.write(fd, audio_bytes)
        os.close(fd)

        # Try GPU transcription first, fall back to ffmpeg+whisper CPU
        proc = await asyncio.create_subprocess_exec(
            "transcribe-gpu",
            tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

        text = stdout.decode().strip() if proc.returncode == 0 else ""

        if not text:
            logger.warning(f"Audio transcription failed (rc={proc.returncode}): {stderr.decode()[:200]}")
            event_bus.emit({"type": "error", "text": "could not transcribe audio"})
            return

        logger.client(f"Transcribed webapp audio: {text[:100]}")
        event_bus.emit(UserEvent(type="user", text=f"[voice] {text}"))
        await message_queue.put((text, True, False))

    except TimeoutError:
        logger.warning("Audio transcription timed out")
        event_bus.emit({"type": "error", "text": "transcription timed out"})
    except Exception as e:
        logger.warning(f"Audio handling error: {e}")
        event_bus.emit({"type": "error", "text": f"audio error: {e}"})
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


async def _send_loop(ws: web.WebSocketResponse, sub: asyncio.Queue[VestaEvent]) -> None:
    try:
        while True:
            event = await sub.get()
            await ws.send_json(event)
    except (ConnectionError, RuntimeError, TypeError, asyncio.CancelledError):
        pass


async def start_ws_server(
    event_bus: EventBus,
    message_queue: asyncio.Queue[tuple[str, bool, bool]],
    state: vm.State,
    config: vm.VestaConfig,
    *,
    host: str = "0.0.0.0",
) -> web.AppRunner:
    app = web.Application()
    app["event_bus"] = event_bus
    app["message_queue"] = message_queue
    app["state"] = state
    app["config"] = config
    app.router.add_get("/ws", _ws_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, config.ws_port)
    await site.start()
    return runner
