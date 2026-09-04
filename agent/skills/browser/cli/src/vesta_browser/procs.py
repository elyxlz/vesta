"""Process-group termination shared by both engines: TERM the group, wait, KILL what remains."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

# The grace a caller allows a doomed process group between TERM and KILL: long enough for a python
# child to unwind its `finally`, short enough that a stop path built from several of these still
# finishes inside the daemon's own stop budget.
KILL_GRACE_SECS = 1.0


async def kill_group(process: asyncio.subprocess.Process, grace: float) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), grace)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
