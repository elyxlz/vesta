"""The finance watcher's half of the daemon contract: a death nobody asked for is announced,
a deliberate `finance daemon stop` is not.

The watcher is loaded from its source file rather than imported: it lives in a skill CLI project
of its own, and every symbol these two cases touch is standard library.
"""

import importlib.util
import json
import os
import pathlib as pl
import signal
import time

import pytest

WATCHER_PY = pl.Path(__file__).resolve().parents[1] / "skills/enable-banking/cli/src/finance_cli/transaction_watcher.py"

# A signal is delivered between bytecodes, so the wait is a formality; the budget only exists so a
# handler that never runs fails the case instead of hanging it.
SIGTERM_BUDGET_SECS = 5
SIGTERM_POLL_SECS = 0.01


def _load_watcher():
    spec = importlib.util.spec_from_file_location("finance_transaction_watcher", WATCHER_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def watcher(tmp_path, monkeypatch):
    """The module with its notifications directory pointed at tmp_path, and the process's own
    SIGTERM disposition put back afterwards: serve() installs a handler on the running process."""
    module = _load_watcher()
    monkeypatch.setattr(module, "NOTIFICATIONS_DIR", tmp_path / "notifications")
    previous = signal.getsignal(signal.SIGTERM)
    yield module
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
