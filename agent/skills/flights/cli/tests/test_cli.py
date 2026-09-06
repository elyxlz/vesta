"""Tests for the flights CLI result shaping, no network."""

from __future__ import annotations

import types
from datetime import date, datetime, timedelta

import fli.search
import pytest
from fli.models import Airline, Airport, FlightLeg, FlightResult
from flights_cli import cli as cli_mod


# FlightSegment validates that the travel date is not in the past, and _search_flights catches that
# ValidationError and returns an {"error": ...} row. A hardcoded literal date therefore does not fail
# this suite on the day it is written; it fails silently at midnight on that date, in every PR against
# master, as a KeyError on a key the error row does not carry. Keep every date here relative to today.
_TRAVEL_DATE = date.today() + timedelta(days=30)
_DEPARTS = datetime.combine(_TRAVEL_DATE, datetime.min.time()).replace(hour=10)


def _flight(price: float = 114.0, stops: int = 0) -> FlightResult:
    leg = FlightLeg(
        airline=Airline.BA,
        flight_number="BA123",
        departure_airport=Airport.FCO,
        arrival_airport=Airport.LHR,
        departure_datetime=_DEPARTS,
        arrival_datetime=_DEPARTS.replace(hour=12),
        duration=120,
    )
    return FlightResult(legs=[leg], price=price, currency="GBP", duration=120, stops=stops)


def _search(monkeypatch: pytest.MonkeyPatch, results: list[FlightResult]) -> list[dict]:
    monkeypatch.setattr(fli.search, "SearchFlights", lambda: types.SimpleNamespace(search=lambda filters, currency: results))
    return cli_mod._search_flights(cli_mod.FlightSearchQuery(origin="FCO", destination="LHR", date=_TRAVEL_DATE.isoformat(), max_results=10))


def test_search_keeps_the_cheapest_nonstop_when_the_page_would_drop_every_nonstop(monkeypatch, capsys):
    connections = [_flight(price=100.0 + i, stops=1) for i in range(10)]
    out = _search(monkeypatch, [*connections, _flight(price=180.0), _flight(price=150.0)])
    assert [r["price"] for r in out] == [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 150.0]
    assert [r["stops"] for r in out] == [1, 1, 1, 1, 1, 1, 1, 1, 1, 0]
    assert "NOTE: omitted_nonstops: 1" in capsys.readouterr().err


@pytest.mark.parametrize(
    "results",
    [
        [_flight(price=100.0), *[_flight(price=101.0 + i, stops=1) for i in range(10)], _flight(price=120.0)],
        [_flight(price=100.0 + i, stops=1) for i in range(12)],
    ],
    ids=["a nonstop already in the page", "no nonstop past the page"],
)
def test_search_returns_the_first_page_unchanged_otherwise(monkeypatch, capsys, results):
    out = _search(monkeypatch, results)
    assert [r["price"] for r in out] == [r.price for r in results[:10]]
    assert capsys.readouterr().err == ""


def test_flight_to_dict_reports_price_with_the_requested_currency():
    out = cli_mod._flight_to_dict(_flight(), currency="GBP")
    assert out["price"] == 114.0
    assert out["currency"] == "GBP"
    assert "price_usd" not in out


def test_flight_to_dict_defaults_to_the_default_currency():
    assert cli_mod._flight_to_dict(_flight())["currency"] == cli_mod.DEFAULT_CURRENCY
