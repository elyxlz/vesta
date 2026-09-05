"""What every child process here shares: the env it starts from, and the group termination that ends it."""

from __future__ import annotations

import asyncio
import contextlib
import os
import pathlib as pl
import signal
import typing as tp

# The grace a caller allows a doomed process group between TERM and KILL: long enough for a python
# child to unwind its `finally`, short enough that a stop path built from several of these still
# finishes inside the daemon's own stop budget.
KILL_GRACE_SECS = 1.0
FALLBACK_PATH = "/usr/local/bin:/usr/bin:/bin"


def base_env() -> dict[str, str]:
    """The closed env every child starts from: a child inherits what this names and nothing else."""
    return {"PATH": os.environ["PATH"] if "PATH" in os.environ else FALLBACK_PATH, "HOME": str(pl.Path.home())}


async def kill_group(process: asyncio.subprocess.Process, grace: float) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), grace)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()


@contextlib.asynccontextmanager
async def reaped_on_failure(process: asyncio.subprocess.Process, grace: float) -> tp.AsyncIterator[None]:
    """Kills `process`'s group if anything escapes the block, a cancellation included, then re-raises."""
    try:
        yield
    except BaseException:
        await kill_group(process, grace)
        raise


async def run_capture(argv: list[str], timeout: float) -> tuple[int | None, str, str]:
    """One bounded child: (exit code, stdout, stderr), with `None` for a child killed at `timeout`.
    A binary that cannot be spawned raises the OSError as is."""
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        # The group, not the process: a helper shells out to curl, which would outlive its parent.
        await kill_group(process, KILL_GRACE_SECS)
        return None, "", ""
    return process.returncode, out.decode(errors="replace").strip(), err.decode(errors="replace").strip()
