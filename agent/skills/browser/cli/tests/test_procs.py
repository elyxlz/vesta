"""The children ledger: what a daemon records of each process it spawns, and the reap that ends
what a dead daemon left running."""

import asyncio
import contextlib
import os
import signal
import sys

from vesta_browser import procs

from .waiting import pid_alive, wait_for_file, wait_until_all_dead

SLEEPER = "import time; time.sleep(60)"
# A child that starts a grandchild in its own process group and writes that pid to argv[1].
FORKER = (
    "import pathlib, subprocess, sys, time; "
    "grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
    "pathlib.Path(sys.argv[1]).write_text(str(grandchild.pid)); time.sleep(60)"
)
REAP_GRACE_SECS = 2.0


async def _sleeper(code: str = SLEEPER, *args: str) -> asyncio.subprocess.Process:
    """A throwaway process leading its own session, so a group signal reaches it and nothing else."""
    return await asyncio.create_subprocess_exec(sys.executable, "-c", code, *args, start_new_session=True)


async def _end(*processes: asyncio.subprocess.Process) -> None:
    for process in processes:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()


def test_record_appends_one_line_and_leaves_every_other_line_alone(tmp_path):
    """Appending is what lets two spawns record at once without a lock; a stale line costs nothing
    until the reap, which is the one reader."""
    ledger = tmp_path / "children"
    ledger.write_text("999999 1\n")

    async def run():
        first, second = await asyncio.gather(_sleeper(), _sleeper())
        try:
            await asyncio.gather(asyncio.to_thread(procs.record, ledger, first.pid), asyncio.to_thread(procs.record, ledger, second.pid))
            expected = {f"{first.pid} {procs.starttime(first.pid)}", f"{second.pid} {procs.starttime(second.pid)}"}
            return ledger.read_text().splitlines(), expected
        finally:
            await _end(first, second)

    lines, expected = asyncio.run(run())
    assert lines[0] == "999999 1"
    assert set(lines[1:]) == expected and len(lines) == 3


def test_reap_ends_recorded_children_by_group_trusts_a_bare_pid_and_leaves_a_recycled_pid_alone(tmp_path):
    ledger = tmp_path / "children"
    grandchild_record = tmp_path / "grandchild.pid"

    async def run():
        gone = await asyncio.create_subprocess_exec(sys.executable, "-c", "pass")
        await gone.wait()
        forker = await _sleeper(FORKER, str(grandchild_record))
        bare, stranger = await asyncio.gather(_sleeper(), _sleeper())
        try:
            await wait_for_file(grandchild_record)
            grandchild = int(grandchild_record.read_text())
            ledger.write_text(f"{gone.pid} 1\n{forker.pid} {procs.starttime(forker.pid)}\n{bare.pid}\n{stranger.pid} 1\n")
            count = await asyncio.to_thread(procs.reap, ledger, REAP_GRACE_SECS)
            dead = await wait_until_all_dead([forker.pid, grandchild, bare.pid])
            return count, dead, pid_alive(stranger.pid), ledger.read_text()
        finally:
            await _end(forker, bare, stranger)

    count, dead, stranger_alive, text = asyncio.run(run())
    assert count == 2
    assert dead is True
    assert stranger_alive is True
    assert text == ""


def test_spawn_records_the_child_as_the_leader_of_its_own_session(tmp_path):
    ledger = tmp_path / "children"

    async def run():
        process = await procs.spawn(ledger, sys.executable, "-c", SLEEPER, env={})
        try:
            line = f"{process.pid} {procs.starttime(process.pid)}"
            return ledger.read_text().splitlines(), line, os.getpgid(process.pid) == process.pid
        finally:
            await _end(process)

    lines, line, leads_its_group = asyncio.run(run())
    assert lines == [line]
    assert leads_its_group is True
