"""Gating tests for the nonstop-recovery follow-up query in `flights search`.

The recovery fires a second stops=0 query only when a one-way default-stops search comes back
with zero nonstops. These tests pin the three gates without any network by exercising the pure
predicate `_should_recover_nonstops`.
"""

import types

from flights_cli.cli import DEFAULT_STOPS, _should_recover_nonstops


def _args(stops=DEFAULT_STOPS, return_date=None):
    return types.SimpleNamespace(stops=stops, return_date=return_date)


# A default one-way search whose results contain no nonstop (no r["stops"] == 0) should recover.
def test_oneway_no_nonstop_triggers():
    results = [{"stops": 1, "price_usd": 100}, {"stops": 2, "price_usd": 90}]
    assert _should_recover_nonstops(_args(), results) is True


# If a nonstop is already present, there is nothing to recover.
def test_oneway_with_nonstop_does_not_trigger():
    results = [{"stops": 0, "price_usd": 200}, {"stops": 1, "price_usd": 100}]
    assert _should_recover_nonstops(_args(), results) is False


# Round trips have no top-level "stops" key, so recovery must NOT fire (would waste a query each time).
def test_roundtrip_does_not_trigger():
    results = [{"price_usd": 300, "outbound": {"legs": []}, "return": {"legs": []}}]
    assert _should_recover_nonstops(_args(return_date="2026-08-25"), results) is False


# An explicit --stops means the caller already chose; do not second-guess it.
def test_explicit_stops_does_not_trigger():
    results = [{"stops": 1, "price_usd": 100}]
    assert _should_recover_nonstops(_args(stops="1"), results) is False


# Nothing came back at all: recovery has no anchor set to union against, so it stays off.
def test_empty_results_does_not_trigger():
    assert _should_recover_nonstops(_args(), []) is False
