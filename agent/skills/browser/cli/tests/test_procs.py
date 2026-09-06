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


def test_record_drops_dead_and_recycled_lines_and_appends_the_new_child(tmp_path):
    ledger = tmp_path / "children"

    async def run():
        gone = await asyncio.create_subprocess_exec(sys.executable, "-c", "pass")
        await gone.wait()
        kept, mismatched, fresh = await asyncio.gather(_sleeper(), _sleeper(), _sleeper())
        try:
            ledger.write_text(f"{gone.pid} 1\n{mismatched.pid} 1\n{kept.pid} {procs.starttime(kept.pid)}\n")
            await asyncio.to_thread(procs.record, ledger, fresh.pid)
            expected = [f"{kept.pid} {procs.starttime(kept.pid)}", f"{fresh.pid} {procs.starttime(fresh.pid)}"]
            return ledger.read_text().splitlines(), expected
        finally:
            await _end(kept, mismatched, fresh)

    lines, expected = asyncio.run(run())
    assert lines == expected


def test_reap_ends_recorded_children_by_group_trusts_a_bare_pid_and_leaves_a_recycled_pid_alone(tmp_path):
    ledger = tmp_path / "children"
    grandchild_record = tmp_path / "grandchild.pid"

    async def run():
        forker = await _sleeper(FORKER, str(grandchild_record))
        bare, stranger = await asyncio.gather(_sleeper(), _sleeper())
        try:
            await wait_for_file(grandchild_record)
            grandchild = int(grandchild_record.read_text())
            ledger.write_text(f"{forker.pid} {procs.starttime(forker.pid)}\n{bare.pid}\n{stranger.pid} 1\n")
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
