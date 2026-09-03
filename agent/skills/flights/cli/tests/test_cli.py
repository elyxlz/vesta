"""Tests for the flights CLI result shaping, no network."""

from __future__ import annotations

from datetime import datetime

from fli.models import Airline, Airport, FlightLeg, FlightResult
from flights_cli import cli as cli_mod


def _flight() -> FlightResult:
    leg = FlightLeg(
        airline=Airline.BA,
        flight_number="BA123",
        departure_airport=Airport.FCO,
        arrival_airport=Airport.LHR,
        departure_datetime=datetime(2026, 9, 5, 10, 0),
        arrival_datetime=datetime(2026, 9, 5, 12, 0),
        duration=120,
    )
    return FlightResult(legs=[leg], price=114.0, currency="GBP", duration=120, stops=0)


def test_flight_to_dict_reports_price_with_the_requested_currency():
    out = cli_mod._flight_to_dict(_flight(), currency="GBP")
    assert out["price"] == 114.0
    assert out["currency"] == "GBP"
    assert "price_usd" not in out


def test_flight_to_dict_defaults_to_the_default_currency():
    assert cli_mod._flight_to_dict(_flight())["currency"] == cli_mod.DEFAULT_CURRENCY
