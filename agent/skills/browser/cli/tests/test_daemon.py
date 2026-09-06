"""The daemon's pid record: the identity rule it shares with the children ledger."""

import os

from vesta_browser import daemon, procs
from vesta_browser.runtime_paths import load_paths


def test_the_record_is_the_pid_and_its_starttime():
    pid = os.getpid()
    assert daemon._record(pid) == f"{pid} {procs.starttime(pid)}"


def test_live_pid_trusts_a_bare_pid_and_refuses_a_recycled_one(tmp_path):
    paths = load_paths({}, tmp_path)
    paths.daemons_dir.mkdir(parents=True)
    record = paths.daemons_dir / "browser.pid"
    record.write_text(str(os.getpid()))
    trusted = daemon.live_pid(paths)
    record.write_text(f"{os.getpid()} 1")
    recycled = daemon.live_pid(paths)
    assert trusted == os.getpid()
    assert recycled is None
