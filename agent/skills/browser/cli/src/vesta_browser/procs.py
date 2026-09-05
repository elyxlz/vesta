"""What every child process here shares: the env it starts from, and the group termination that ends it."""

from __future__ import annotations

import asyncio
import contextlib
import os
import pathlib as pl
import signal

# The grace a caller allows a doomed process group between TERM and KILL: long enough for a python
# child to unwind its `finally`, short enough that a stop path built from several of these still
# finishes inside the daemon's own stop budget.
KILL_GRACE_SECS = 1.0
FALLBACK_PATH = "/usr/local/bin:/usr/bin:/bin"


def path_env() -> str:
    return os.environ["PATH"] if "PATH" in os.environ else FALLBACK_PATH


def base_env() -> dict[str, str]:
    """The closed env every child starts from: a child inherits what this names and nothing else."""
    return {"PATH": path_env(), "HOME": str(pl.Path.home())}


async def kill_group(process: asyncio.subprocess.Process, grace: float) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), grace)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
