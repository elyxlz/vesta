"""The plumbing every provider socket shares: a reader task, an event queue, and the close.

A provider's stream subclasses SocketStream and says three things: how mic audio goes out
(`send`), how a commit is asked for (`commit`), and what one message of the provider means
(`_event`). The base guarantees the contract's ending: `closed` is always the last event,
whether the provider hung up, sent something unreadable, or the engine closed the stream.
"""

import asyncio
import contextlib
import json
import logging
import typing as tp

import aiohttp

from voice.settings import JsonValue

from .base import SttEvent

logger = logging.getLogger("voice.stream")

CLOSED: SttEvent = {"kind": "closed", "text": ""}


class SocketStream:
    def __init__(self, session: aiohttp.ClientSession, ws: aiohttp.ClientWebSocketResponse) -> None:
        self._session = session
        self._ws = ws
        self._queue: asyncio.Queue[SttEvent] = asyncio.Queue()
        self._reader = asyncio.create_task(self._read())

    async def close(self) -> None:
        self._reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reader
        await self._ws.close()
        await self._session.close()

    async def events(self) -> tp.AsyncIterator[SttEvent]:
        while True:
            event = await self._queue.get()
            yield event
            if event["kind"] == "closed":
                return

    def _emit(self, event: SttEvent) -> None:
        self._queue.put_nowait(event)

    def _event(self, message: dict[str, JsonValue]) -> SttEvent | None:
        """The event one provider message means, or None for a message that means none."""
        raise NotImplementedError

    async def _read(self) -> None:
        try:
            async for msg in self._ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                event = self._event(json.loads(msg.data))
                if event is not None:
                    self._emit(event)
        except (ValueError, KeyError, TypeError) as e:
            logger.error("%s got a message it cannot read: %s", type(self).__name__, e)
        finally:
            self._emit(CLOSED)
