"""The `/stt/listen` socket: live transcription with no engine session.

LEGACY(remove-when: MIN_SUPPORTED_CLIENT_VERSION in vestad is 0.3.19 or higher): an app build
older than that hears through this route, and each newer stock client uses `/voice/session`.

The client sends mic audio as binary frames (pcm_s16le, 16 kHz, mono) and reads `TurnInfo` text
frames: `StartOfTurn` when a turn has its first words, `Update` for each later live text, and
`EndOfTurn` with the final text. The frames come from the events of an `SttStream`, so the route
works with each STT provider.
"""

import asyncio
import json
import logging
import typing as tp

import aiohttp
from aiohttp import web

from .providers.base import SttEvent, SttStream

logger = logging.getLogger("voice.listen")


class TurnInfo(tp.TypedDict):
    type: tp.Literal["TurnInfo"]
    event: tp.Literal["StartOfTurn", "Update", "EndOfTurn"]
    transcript: str


def _frame(event: tp.Literal["StartOfTurn", "Update", "EndOfTurn"], transcript: str) -> TurnInfo:
    return {"type": "TurnInfo", "event": event, "transcript": transcript}


def turn_frames(turn_open: bool, event: SttEvent) -> tuple[bool, list[TurnInfo]]:
    """The frames one stream event means, and if a turn is open after it. A turn opens on its
    first words, so a commit with no words outside a turn means nothing."""
    text = event["text"]
    if not turn_open and not text.strip():
        return False, []
    if event["kind"] == "transcription":
        return True, [_frame("Update" if turn_open else "StartOfTurn", text)]
    opening = [] if turn_open else [_frame("StartOfTurn", text)]
    return False, [*opening, _frame("EndOfTurn", text)]


async def _audio_in(ws: web.WebSocketResponse, stream: SttStream) -> None:
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.BINARY:
            await stream.send(msg.data)


async def _frames_out(ws: web.WebSocketResponse, stream: SttStream) -> None:
    turn_open = False
    async for event in stream.events():
        if event["kind"] == "closed":
            return
        turn_open, frames = turn_frames(turn_open, event)
        for frame in frames:
            await ws.send_str(json.dumps(frame))


async def _end(tasks: list[asyncio.Task[None]], stream: SttStream) -> None:
    for task in tasks:
        task.cancel()
    for result in await asyncio.gather(*tasks, return_exceptions=True):
        if isinstance(result, Exception) and not isinstance(result, ConnectionError):
            logger.error("listen socket task failed", exc_info=result)
    await stream.close()


async def relay(ws: web.WebSocketResponse, stream: SttStream) -> None:
    """Run one listen socket until the client or the provider goes, then close the stream."""
    tasks = [asyncio.create_task(_audio_in(ws, stream)), asyncio.create_task(_frames_out(ws, stream))]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        await asyncio.shield(_end(tasks, stream))
