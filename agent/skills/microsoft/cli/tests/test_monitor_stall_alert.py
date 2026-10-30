"""A unit that stays unreadable must page the agent once, and say once when it reads again.

A failing unit keeps its watermark, so nothing is lost, but without a notification the agent is blind
to that unit until it happens to read the monitor log. The alert keys off the persisted watermark and
`last_cycle`, so a short blip and a catch-up after daemon downtime stay quiet, and a daemon restart in
the middle of a stall neither repeats the page nor loses the recovery notice.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from microsoft_cli import monitor
from microsoft_cli.context import MicrosoftContext

UNIT = "mail:a@example.com"


class _Ctx:
    def __init__(self, notif_dir: Path) -> None:
        self.monitor_logger = logging.getLogger("test-monitor-stall")
        self.notif_dir = notif_dir


def _types(notif_dir: Path) -> list[str]:
    return [json.loads(p.read_text())["type"] for p in sorted(notif_dir.glob("*.json"))]


def _fail(_last_dt, _catching_up):
    return None


def _cycle(ctx: _Ctx, state: monitor.MonitorState, now: datetime, poll) -> None:
    """One monitor cycle for one unit, persisting last_cycle the way `run` does."""
    monitor._poll_unit(cast("MicrosoftContext", ctx), state, UNIT, now, poll)
    state["last_cycle"] = now.isoformat()


def _healthy_until(start: datetime) -> monitor.MonitorState:
    return {"last_cycle": start.isoformat(), "units": {UNIT: start.isoformat()}}


def test_a_long_stall_pages_once(tmp_path: Path) -> None:
    start = datetime.now(UTC)
    state = _healthy_until(start)
    ctx = _Ctx(tmp_path)

    for minute in range(1, 61):
        _cycle(ctx, state, start + timedelta(minutes=minute), _fail)

    assert _types(tmp_path) == ["monitor_stalled"]
    notif = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert notif["interrupt"] is True
    assert notif["unit"] == UNIT
    assert notif["behind_minutes"] == 30


def test_recovery_after_a_stall_is_reported_once(tmp_path: Path) -> None:
    start = datetime.now(UTC)
    state = _healthy_until(start)
    ctx = _Ctx(tmp_path)

    for minute in range(1, 41):
        _cycle(ctx, state, start + timedelta(minutes=minute), _fail)
    for minute in range(41, 44):
        now = start + timedelta(minutes=minute)
        _cycle(ctx, state, now, lambda _l, _c, now=now: now)

    assert _types(tmp_path) == ["monitor_stalled", "monitor_recovered"]
    recovered = json.loads(max(tmp_path.glob("*.json")).read_text())
    assert recovered["interrupt"] is False


def test_a_short_blip_stays_quiet(tmp_path: Path) -> None:
    start = datetime.now(UTC)
    state = _healthy_until(start)
    ctx = _Ctx(tmp_path)

    for minute in range(1, 6):
        _cycle(ctx, state, start + timedelta(minutes=minute), _fail)
    now = start + timedelta(minutes=6)
    _cycle(ctx, state, now, lambda _l, _c: now)

    assert _types(tmp_path) == []


def test_a_successful_catch_up_after_downtime_does_not_page(tmp_path: Path) -> None:
    """A daemon that was simply off and reads fine on restart was never blind while running."""
    start = datetime.now(UTC)
    state = _healthy_until(start)
    ctx = _Ctx(tmp_path)

    now = start + timedelta(hours=3)
    _cycle(ctx, state, now, lambda _l, _c: now)

    assert _types(tmp_path) == []


def test_a_restart_mid_stall_does_not_page_again(tmp_path: Path) -> None:
    """Only the persisted state carries over a restart; the page must not repeat, the recovery must still come."""
    start = datetime.now(UTC)
    state = _healthy_until(start)
    ctx = _Ctx(tmp_path)

    for minute in range(1, 41):
        _cycle(ctx, state, start + timedelta(minutes=minute), _fail)
    restarted = json.loads(json.dumps(state))
    _cycle(ctx, restarted, start + timedelta(minutes=90), _fail)
    now = start + timedelta(minutes=91)
    _cycle(ctx, restarted, now, lambda _l, _c: now)

    assert _types(tmp_path) == ["monitor_stalled", "monitor_recovered"]
