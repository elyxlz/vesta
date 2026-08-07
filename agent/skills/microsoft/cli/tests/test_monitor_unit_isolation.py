"""One failing unit must not take the whole monitor cycle down with it.

`state["last_cycle"]` and the unit watermarks are persisted only after every unit has run, so an
exception escaping one unit's poll to the loop-level handler would leave all of them unwritten:
every account then re-reads its whole window next cycle and re-notifies the same messages, and a
persistent failure in one unit (a mis-provisioned Teams account raising on every cycle) would
freeze the fleet of watermarks indefinitely.

`_poll_unit` therefore contains any exception from its poll: the failing unit's watermark stays
where it was, the other units carry on, and the cycle still persists.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from microsoft_cli import backend, monitor


class _Ctx:
    def __init__(self) -> None:
        import logging

        self.monitor_logger = logging.getLogger("test-monitor")


def _state(last_cycle: datetime) -> monitor.MonitorState:
    return {"last_cycle": last_cycle.isoformat(), "units": {}}


def test_a_raising_poll_leaves_that_units_watermark_untouched() -> None:
    now = datetime.now(UTC)
    state = _state(now - timedelta(minutes=5))

    def boom(_last_dt, _catching_up):
        raise backend.GraphUnavailableError("no Teams token for someone@example.com")

    monitor._poll_unit(_Ctx(), state, "teams:someone@example.com", now, boom)

    assert state["units"]["teams:someone@example.com"] == (now - timedelta(minutes=5)).isoformat()


def test_a_raising_poll_does_not_propagate() -> None:
    """An exception escaping to the loop-level handler would abandon the whole cycle."""
    now = datetime.now(UTC)
    state = _state(now - timedelta(minutes=5))

    def boom(_last_dt, _catching_up):
        raise RuntimeError("anything at all")

    monitor._poll_unit(_Ctx(), state, "mail:someone@example.com", now, boom)


def test_later_units_still_advance_after_an_earlier_one_fails() -> None:
    now = datetime.now(UTC)
    earlier = now - timedelta(minutes=5)
    state = _state(earlier)

    def boom(_last_dt, _catching_up):
        raise backend.GraphUnavailableError("no Teams token")

    monitor._poll_unit(_Ctx(), state, "teams:a@example.com", now, boom)
    monitor._poll_unit(_Ctx(), state, "mail:a@example.com", now, lambda _l, _c: now)

    assert state["units"]["teams:a@example.com"] == earlier.isoformat()
    assert state["units"]["mail:a@example.com"] == now.isoformat()


def test_a_successful_poll_still_advances_normally() -> None:
    now = datetime.now(UTC)
    state = _state(now - timedelta(minutes=5))

    monitor._poll_unit(_Ctx(), state, "mail:a@example.com", now, lambda _l, _c: now)

    assert state["units"]["mail:a@example.com"] == now.isoformat()


def test_a_poll_reporting_it_read_nothing_keeps_its_watermark() -> None:
    now = datetime.now(UTC)
    earlier = now - timedelta(minutes=5)
    state = _state(earlier)

    monitor._poll_unit(_Ctx(), state, "mail:a@example.com", now, lambda _l, _c: None)

    assert state["units"]["mail:a@example.com"] == earlier.isoformat()


@pytest.mark.parametrize(
    "exc",
    [
        backend.GraphUnavailableError("no Teams token"),
        RuntimeError("network blip"),
        ValueError("malformed response"),
    ],
)
def test_any_exception_type_is_contained(exc: Exception) -> None:
    now = datetime.now(UTC)
    state = _state(now - timedelta(minutes=5))

    def boom(_last_dt, _catching_up):
        raise exc

    monitor._poll_unit(_Ctx(), state, "unit:x", now, boom)
    assert state["units"]["unit:x"] == (now - timedelta(minutes=5)).isoformat()
