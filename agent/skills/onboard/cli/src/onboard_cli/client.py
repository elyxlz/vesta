"""Thin HTTP client for the vesta-cloud onboarding endpoints.

Two real network calls, both public (no api_key): subdomain availability and the
reserve-and-checkout that returns a Stripe Checkout URL. The referral code, when
present, rides in the `X-Vesta-Referral` header exactly as the control plane
expects (a non-secret, per-server attribution id).
"""

from __future__ import annotations

from typing import Any

import requests

from .config import Config

_TIMEOUT = 20


class OnboardError(Exception):
    """A control-plane call failed (network, HTTP, or a structured API error)."""


class Client:
    def __init__(self, config: Config) -> None:
        self._cfg = config

    def _url(self, path: str) -> str:
        return f"{self._cfg.base_url}{path}"

    def check(self, subdomain: str) -> dict[str, Any]:
        """GET /api/onboard/check?subdomain=<s> -> {subdomain, available, reason?}."""
        try:
            resp = requests.get(
                self._url("/onboard/check"),
                params={"subdomain": subdomain},
                timeout=_TIMEOUT,
            )
        except requests.RequestException as e:
            raise OnboardError(f"could not reach the control plane: {e}") from e
        return self._json(resp)

    def checkout(
        self,
        *,
        email: str,
        subdomain: str,
        plan: str,
        seed: dict[str, Any] | None,
        referral_code: str | None,
        price: float | None = None,
    ) -> dict[str, Any]:
        """POST /api/onboard/checkout -> {url} (or 409 taken / 429 rate-limited)."""
        body: dict[str, Any] = {"email": email, "subdomain": subdomain, "plan": plan}
        if seed:
            body["seed"] = seed
        if price is not None:
            # Negotiated MONTHLY price (USD). The control plane enforces the floor.
            body["price"] = price
        headers = {}
        if referral_code:
            headers["X-Vesta-Referral"] = referral_code
        try:
            resp = requests.post(
                self._url("/onboard/checkout"),
                json=body,
                headers=headers,
                timeout=_TIMEOUT,
            )
        except requests.RequestException as e:
            raise OnboardError(f"could not reach the control plane: {e}") from e
        return self._json(resp)

    @staticmethod
    def _json(resp: requests.Response) -> dict[str, Any]:
        try:
            data = resp.json()
        except ValueError:
            raise OnboardError(f"control plane returned non-JSON ({resp.status_code}): {resp.text[:200]}") from None
        # 4xx bodies carry a structured {error} the skill should surface verbatim
        # (e.g. "subdomain taken", "rate limited") rather than raise opaquely.
        if resp.status_code >= 500:
            raise OnboardError(f"control plane error {resp.status_code}: {data}")
        return data
