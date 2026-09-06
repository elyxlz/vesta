"""What every child process here shares: the env it starts from, the ledger that records it, and
the group termination that ends it."""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import pathlib as pl
import signal
import tempfile
import time
import typing as tp

# The grace a caller allows a doomed process group between TERM and KILL: long enough for a python
# child to unwind its `finally`, short enough that a stop path built from several of these still
# finishes inside the daemon's own stop budget.
KILL_GRACE_SECS = 1.0
FALLBACK_PATH = "/usr/local/bin:/usr/bin:/bin"
# The ledger of every child a daemon spawned, one `<pid> <starttime>` line each, under the daemon's
# root. The daemon that starts next reads it and ends whatever the last one left running.
LEDGER_NAME = "children"
REAP_POLL_SECS = 0.05

# A process as recorded: its pid and the starttime read when it was recorded, None where /proc gave none.
Identity = tuple[int, int | None]


def base_env() -> dict[str, str]:
    """The closed env every child starts from: a child inherits what this names and nothing else."""
    return {"PATH": os.environ["PATH"] if "PATH" in os.environ else FALLBACK_PATH, "HOME": str(pl.Path.home())}


def starttime(pid: int) -> int | None:
    """Field 22 of /proc/<pid>/stat: the process start time in clock ticks since boot.

    A recycled pid cannot share the original's starttime, because the process that took the pid
    necessarily started later, so (pid, starttime) is a stable identity. Returns None where /proc
    is unreadable, which drops the caller back to a bare pid-existence check.
    """
    try:
        stat = pl.Path(f"/proc/{pid}/stat").read_text()
        # comm is a bracketed field that may itself contain spaces and parentheses, so the
        # numbered fields resume after the LAST ')'.
        return int(stat[stat.rindex(")") + 2 :].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _line(identity: Identity) -> str:
    pid, started = identity
    return f"{pid} {started}" if started is not None else str(pid)


def _parse(line: str) -> Identity | None:
    fields = line.split()
    if not fields or not fields[0].isdigit():
        return None
    return int(fields[0]), (int(fields[1]) if len(fields) > 1 and fields[1].isdigit() else None)


def _entries(ledger: pl.Path) -> list[Identity]:
    if not ledger.exists():
        return []
    return [identity for line in ledger.read_text().splitlines() if (identity := _parse(line)) is not None]


def _alive(identity: Identity) -> bool:
    """Whether the process recorded as `identity` still runs. A record with no starttime is trusted
    on pid existence alone, as is one whose current starttime cannot be read."""
    pid, recorded = identity
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    current = starttime(pid)
    return recorded is None or current is None or current == recorded


def _write(ledger: pl.Path, entries: list[Identity]) -> None:
    handle, staged = tempfile.mkstemp(dir=ledger.parent, prefix=f"{ledger.name}-")
    with os.fdopen(handle, "w") as staged_file:
        staged_file.write("".join(f"{_line(identity)}\n" for identity in entries))
    pl.Path(staged).replace(ledger)


def record(ledger: pl.Path, pid: int) -> None:
    """Adds `pid` to the ledger and drops every line no live process answers to. Each write is a
    whole file, so two spawns recording at once serialize on the lock beside it."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.with_name(f"{ledger.name}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        kept = [identity for identity in _entries(ledger) if _alive(identity)]
        _write(ledger, [*kept, (pid, starttime(pid))])


def _signal(pid: int, signum: int) -> None:
    """Signals the group `pid` leads, or `pid` alone when it leads none; a process already gone is
    the outcome asked for."""
    try:
        os.killpg(pid, signum)
    except ProcessLookupError:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signum)


def end_processes(entries: list[Identity], grace: float) -> int:
    """SIGTERM to every entry still running, then SIGKILL to whatever still answers `grace` later.
    Blocking: run it off the loop. Returns how many entries were running."""
    live = [identity for identity in entries if _alive(identity)]
    for pid, _ in live:
        _signal(pid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(_alive(identity) for identity in live):
        time.sleep(REAP_POLL_SECS)
    for identity in live:
        if _alive(identity):
            _signal(identity[0], signal.SIGKILL)
    return len(live)


def reap(ledger: pl.Path, grace: float) -> int:
    """Ends every process the ledger names that still runs, then empties the ledger."""
    count = end_processes(_entries(ledger), grace)
    _write(ledger, [])
    return count


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


async def spawn(
    ledger: pl.Path,
    *argv: str,
    env: dict[str, str],
    stdin: int | None = None,
    stdout: int | tp.BinaryIO | None = None,
    stderr: int | tp.BinaryIO | None = None,
) -> asyncio.subprocess.Process:
    """A child leading its own session, recorded in `ledger` before the caller holds it, so the
    daemon that starts next can end it if this one dies holding the handle."""
    process = await asyncio.create_subprocess_exec(*argv, env=env, start_new_session=True, stdin=stdin, stdout=stdout, stderr=stderr)
    async with reaped_on_failure(process, KILL_GRACE_SECS):
        await asyncio.to_thread(record, ledger, process.pid)
    return process


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
