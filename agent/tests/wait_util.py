"""Deadline-polling helper for test synchronization.

Replaces sleep-based synchronization ("sleep 0.1s and hope the background task
ran") with explicit condition polling: tests state WHAT they are waiting for,
and flake only if the condition genuinely never becomes true within the timeout.
"""

import asyncio
import time
import typing as tp

WAIT_TIMEOUT_S = 5.0
POLL_INTERVAL_S = 0.005


async def wait_for_condition(predicate: tp.Callable[[], bool], *, timeout: float = WAIT_TIMEOUT_S, message: str = "") -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError(message or f"condition not met within {timeout}s")
        await asyncio.sleep(POLL_INTERVAL_S)
