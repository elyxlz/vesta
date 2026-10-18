"""A cap on the TTS syntheses that run at the same time, one cap for each provider.

A provider account allows only so many requests at once (ElevenLabs: 3 on some plans, fewer or
more on others), and that limit is per account, so the cap is shared by every session of this
process. Waiters get a slot in the order they asked for one, so the first reply of a burst never
waits behind a later one.

A provider that hears "too many requests at once" calls `lower`, and the cap stays lower for the
rest of the process.
"""

import asyncio
import collections
import contextlib
import logging

logger = logging.getLogger("voice.limit")

DEFAULT_TTS_CONCURRENCY = 2


class Limiter:
    def __init__(self, name: str, cap: int = DEFAULT_TTS_CONCURRENCY) -> None:
        self.name = name
        self.cap = cap
        self.active = 0
        self._waiters: collections.deque[asyncio.Future[None]] = collections.deque()

    async def acquire(self) -> None:
        if self.active < self.cap and not self._waiters:
            self.active += 1
            return
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        try:
            await waiter
        except asyncio.CancelledError:
            if waiter.done() and not waiter.cancelled():
                # The slot came just before the cancel: hand it on.
                self.release()
            else:
                with contextlib.suppress(ValueError):
                    self._waiters.remove(waiter)
            raise

    def release(self) -> None:
        self.active -= 1
        self._wake()

    def lower(self) -> None:
        """One slot less for the rest of the process, never fewer than one."""
        if self.cap <= 1:
            return
        self.cap -= 1
        logger.warning("%s refused concurrent requests: tts concurrency cap lowered to %d", self.name, self.cap)

    def _wake(self) -> None:
        while self._waiters and self.active < self.cap:
            waiter = self._waiters.popleft()
            if waiter.done():
                continue
            self.active += 1
            waiter.set_result(None)


_LIMITERS: dict[type, Limiter] = {}


def for_provider(provider: object) -> Limiter:
    """The limiter of a provider, keyed by its class: one vendor, one account limit."""
    kind = type(provider)
    if kind not in _LIMITERS:
        _LIMITERS[kind] = Limiter(kind.__name__)
    return _LIMITERS[kind]


def reset() -> None:
    """Forget every limiter and its learned cap. For tests."""
    _LIMITERS.clear()
