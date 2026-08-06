"""One failing unit must not take the whole monitor cycle down with it.

Observed on a live box with two accounts. The personal account carried a Teams marker written by
`auth setup` saying it authorizes Teams by device flow, but no MSAL Teams token was ever obtained
for it (the tenant walled Graph, so mail went over the OWA REST capture instead). Every cycle,
`resolve_token` therefore reached `graph_token` and raised `backend.GraphUnavailableError`.

Two things went wrong at once:

1. `_poll_teams_account` catches `teams.TeamsError`, and `GraphUnavailableError` is not one of
   those (it subclasses `Exception` directly), so the error escaped its handler.
2. It then escaped `_poll_unit` to the loop-level `except`, which logs and retries the entire
   cycle. Because `state["last_cycle"]` and the unit watermarks are only written after every unit
   has run, *nothing* was persisted, so on the next cycle every account re-read its whole window
   and re-notified the same messages. The watermark sat frozen for eighteen hours and the same
   two dozen emails arrived over and over.

The fix is per-unit isolation, which is what `_poll_unit`'s own docstring already promises: a poll
that fails leaves its watermark where it was and the other units carry on.
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
    """The regression: this used to reach the loop-level handler and abandon the whole cycle."""
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
