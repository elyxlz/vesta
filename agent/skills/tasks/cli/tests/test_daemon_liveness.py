"""A daemon that exited but has not been reaped must not read as running.

start exits as soon as the daemon is up, so the daemon reparents to init. Where init does not reap
(in an agent container PID 1 is the agent process), the pid of a dead daemon lingers indefinitely
and answers a signal-0 probe like a live process. Everything downstream then lies: status reports
running, stop waits out its whole budget and fails, and the next start declines as already_running
while nothing serves the port.
"""

import os
import pathlib
import subprocess
import time

from tasks_cli.daemon import _alive


def _state(pid: int) -> str:
    stat = pathlib.Path(f"/proc/{pid}/stat").read_text()
    return stat[stat.rfind(") ") + 2]


def _zombie() -> subprocess.Popen[bytes]:
    """A genuine zombie: Popen does not reap until wait(), so the exited child stays defunct."""
    proc = subprocess.Popen(["/bin/true"])
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if _state(proc.pid) == "Z":
            return proc
        time.sleep(0.05)
    proc.wait()
    raise AssertionError("could not produce a zombie to test against")


def test_alive_is_false_for_a_real_zombie() -> None:
    proc = _zombie()
    try:
        # The probe the fix replaces would pass here, which is the whole bug.
        os.kill(proc.pid, 0)
        assert not _alive(proc.pid), "unreaped corpse reported alive"
    finally:
        proc.wait()


def test_alive_is_true_for_a_running_process() -> None:
    assert _alive(os.getpid())


def test_alive_is_false_for_a_pid_that_never_existed() -> None:
    # Nothing to read in /proc, which must answer "not alive" rather than raise.
    assert not _alive(2**31 - 1)
