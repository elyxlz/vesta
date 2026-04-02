"""Duffel API client for flight search and booking.

Thin wrapper around the Duffel REST API v2.
Uses requests directly (official Python SDK was archived Sep 2024).
"""

import os
import json
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://api.duffel.com"
TOKEN_FILE = Path.home() / ".config" / "duffel" / "token"


def _get_token() -> str:
    """Read token from env var or file."""
    token = os.environ.get("DUFFEL_TOKEN")
    if token:
        return token.strip()
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    raise RuntimeError("No Duffel API token found. Set DUFFEL_TOKEN env var or write token to ~/.config/duffel/token")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Duffel-Version": "v2",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _check(resp: requests.Response) -> dict:
    """Check response, raise with Duffel error details on failure."""
    if not resp.ok:
        try:
            err = resp.json()
            errors = err.get("errors", [])
            msgs = [e.get("message", str(e)) for e in errors]
            detail = "; ".join(msgs) if msgs else resp.text
        except Exception:
            detail = resp.text
        raise RuntimeError(f"Duffel API error {resp.status_code}: {detail}")
    return resp.json()["data"]


# ---------------------------------------------------------------------------
# Offer Requests (Search)
# ---------------------------------------------------------------------------


def create_offer_request(
    slices: list[dict],
    passengers: list[dict] | None = None,
    cabin_class: str = "economy",
    max_connections: int | None = None,
    return_offers: bool = True,
) -> dict:
    """Create an offer request (search for flights).

    Args:
        slices: List of journey segments, each with origin, destination, departure_date
        passengers: List of passenger specs (default: 1 adult)
        cabin_class: economy, premium_economy, business, first
        max_connections: Max connections per slice (None = any)
        return_offers: If True, offers are returned inline (up to ~2000)

    Returns:
        Full offer request response including offers and passenger IDs
    """
    if passengers is None:
        passengers = [{"type": "adult"}]

    payload: dict[str, Any] = {
        "data": {
            "slices": slices,
            "passengers": passengers,
            "cabin_class": cabin_class,
        }
    }
    if max_connections is not None:
        payload["data"]["max_connections"] = max_connections

    resp = requests.post(
        f"{BASE_URL}/air/offer_requests",
        json=payload,
        headers=_headers(),
        params={"return_offers": str(return_offers).lower()},
    )
    return _check(resp)


def list_offers(
    offer_request_id: str,
    sort: str = "total_amount",
    limit: int = 50,
    max_connections: int | None = None,
) -> list[dict]:
    """List offers for an offer request."""
    params: dict[str, Any] = {
        "offer_request_id": offer_request_id,
        "sort": sort,
        "limit": limit,
    }
    if max_connections is not None:
        params["max_connections"] = max_connections

    resp = requests.get(
        f"{BASE_URL}/air/offers",
        headers=_headers(),
        params=params,
    )
    return _check(resp)


def get_offer(offer_id: str, return_services: bool = True) -> dict:
    """Get a single offer with refreshed pricing."""
    resp = requests.get(
        f"{BASE_URL}/air/offers/{offer_id}",
        headers=_headers(),
        params={"return_available_services": str(return_services).lower()},
    )
    return _check(resp)


# ---------------------------------------------------------------------------
# Orders (Booking)
# ---------------------------------------------------------------------------


def create_order(
    offer_id: str,
    passengers: list[dict],
    payment_type: str = "balance",
    payment_currency: str | None = None,
    payment_amount: str | None = None,
    order_type: str = "instant",
    metadata: dict | None = None,
) -> dict:
    """Create an order (book a flight).

    Args:
        offer_id: The offer to book
        passengers: Passenger details with id, given_name, family_name, title,
                    gender, born_on, email, phone_number
        payment_type: 'balance' (test mode unlimited) or 'card'
        payment_currency: Currency code (auto-detected from offer if None)
        payment_amount: Amount string (auto-detected from offer if None)
        order_type: 'instant' (pay now) or 'hold' (pay later)
        metadata: Optional metadata dict

    Returns:
        Order response with booking_reference, order ID, etc.
    """
    # If currency/amount not provided, fetch offer to get them
    if payment_currency is None or payment_amount is None:
        offer = get_offer(offer_id, return_services=False)
        payment_currency = payment_currency or offer["total_currency"]
        payment_amount = payment_amount or offer["total_amount"]

    payload: dict[str, Any] = {
        "data": {
            "type": order_type,
            "selected_offers": [offer_id],
            "passengers": passengers,
        }
    }

    if order_type == "instant":
        payload["data"]["payments"] = [
            {
                "type": payment_type,
                "currency": payment_currency,
                "amount": payment_amount,
            }
        ]

    if metadata:
        payload["data"]["metadata"] = metadata

    resp = requests.post(
        f"{BASE_URL}/air/orders",
        json=payload,
        headers=_headers(),
    )
    return _check(resp)


def get_order(order_id: str) -> dict:
    """Get order details."""
    resp = requests.get(
        f"{BASE_URL}/air/orders/{order_id}",
        headers=_headers(),
    )
    return _check(resp)


def list_orders(limit: int = 20) -> list[dict]:
    """List recent orders."""
    resp = requests.get(
        f"{BASE_URL}/air/orders",
        headers=_headers(),
        params={"limit": limit},
    )
    return _check(resp)


# ---------------------------------------------------------------------------
# Cancellations
# ---------------------------------------------------------------------------


def cancel_order(order_id: str, confirm: bool = True) -> dict:
    """Cancel an order. If confirm=True, confirms immediately."""
    # Step 1: Create cancellation
    resp = requests.post(
        f"{BASE_URL}/air/order_cancellations",
        json={"data": {"order_id": order_id}},
        headers=_headers(),
    )
    cancellation = _check(resp)

    if confirm:
        # Step 2: Confirm cancellation
        resp = requests.post(
            f"{BASE_URL}/air/order_cancellations/{cancellation['id']}/actions/confirm",
            headers=_headers(),
        )
        cancellation = _check(resp)

    return cancellation


# ---------------------------------------------------------------------------
# Passenger profiles (local convenience)
# ---------------------------------------------------------------------------

PROFILES_FILE = Path.home() / ".config" / "duffel" / "passengers.json"


def load_profiles() -> dict[str, dict]:
    """Load saved passenger profiles."""
    if PROFILES_FILE.exists():
        return json.loads(PROFILES_FILE.read_text())
    return {}


def save_profile(name: str, profile: dict) -> None:
    """Save a passenger profile for reuse."""
    profiles = load_profiles()
    profiles[name] = profile
    PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILES_FILE.write_text(json.dumps(profiles, indent=2))


def get_profile(name: str) -> dict:
    """Get a saved passenger profile by name."""
    profiles = load_profiles()
    if name not in profiles:
        raise RuntimeError(f"No passenger profile '{name}'. Available: {', '.join(profiles.keys()) or 'none'}")
    return profiles[name]
