"""The finance watcher's half of the daemon contract, at unit level: a death nobody asked for is
announced, a deliberate `finance daemon stop` is not.

The end-to-end half lives in the conformance harness (`agent/tests/test_daemon_contract.py`), which
now runs finance with `emits_daemon_died=True` and reads the real notifications directory. These
two cases cover what a black-box harness cannot reach: the class of exception that arrives (a
`MemoryError` rather than the SIGINT the harness can send) and the re-raise that keeps the exit
status intact.
"""

import json
import os
import signal
import time

import pytest
from finance_cli import transaction_watcher as tw

# A signal is delivered between bytecodes, so the wait is a formality; the budget only exists so a
# handler that never runs fails the case instead of hanging it.
SIGTERM_BUDGET_SECS = 5
SIGTERM_POLL_SECS = 0.01


@pytest.fixture
def watcher(tmp_path, monkeypatch):
    """The module with its notifications directory pointed at tmp_path, and the process's own
    SIGTERM disposition put back afterwards: serve() installs a handler on the running process.

    The redirect is a tmp_path so the suite never writes into a real notifications directory, not a
    patch around a wrong destination: `_notifications_dir()` resolves the engine's own path, the
    harness case asserts the notice lands there for real, and `test_transaction_watcher.py` locks
    the resolution itself.
    """
    monkeypatch.setattr(tw, "NOTIFICATIONS_DIR", tmp_path / "notifications")
    previous = signal.getsignal(signal.SIGTERM)
    yield tw
    signal.signal(signal.SIGTERM, previous)


def _notices(watcher) -> list[dict]:
    directory = watcher.NOTIFICATIONS_DIR
    if not directory.exists():
        return []
    return [json.loads(path.read_text()) for path in sorted(directory.glob("*.json"))]


def test_a_death_nobody_asked_for_is_announced_and_still_kills_the_process(watcher, monkeypatch):
    """The poll loop swallows every `Exception`, so what reaches serve() is the silent class:
    a SystemExit, a KeyboardInterrupt, a MemoryError. One notification, and the exception carries
    on so the process still exits."""

    def die() -> None:
        raise MemoryError("out of memory")

    monkeypatch.setattr(watcher, "_poll_forever", die)

    with pytest.raises(MemoryError):
        watcher.serve()

    notices = _notices(watcher)
    assert len(notices) == 1, f"expected exactly one death notice, got {notices}"
    assert notices[0]["type"] == "daemon_died"
    assert notices[0]["interrupt"] is True
    assert "MemoryError" in notices[0]["message"]


def test_a_deliberate_stop_is_never_reported_as_a_crash(watcher, monkeypatch):
    """`finance daemon stop` is a SIGTERM, and an agent woken by its own stop command is exactly
    the false alarm that makes a real one easy to ignore."""

    def stopped() -> None:
        os.kill(os.getpid(), signal.SIGTERM)
        deadline = time.monotonic() + SIGTERM_BUDGET_SECS
        while time.monotonic() < deadline:
            time.sleep(SIGTERM_POLL_SECS)
        raise AssertionError("the SIGTERM handler serve() installed never ran")

    monkeypatch.setattr(watcher, "_poll_forever", stopped)

    with pytest.raises(SystemExit) as exit_info:
        watcher.serve()

    assert exit_info.value.code == 0
    assert _notices(watcher) == []
