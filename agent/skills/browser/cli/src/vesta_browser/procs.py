"""Process-group termination shared by both engines: TERM the group, wait, KILL what remains."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal


async def kill_group(process: asyncio.subprocess.Process, grace: float) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), grace)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
