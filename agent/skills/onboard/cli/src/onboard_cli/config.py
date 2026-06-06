"""Configuration for the onboard CLI.

Everything is read from the environment: the control-plane base URL and (for
hosted vestas) the non-secret referral code that attributes a completed signup to
this account. The ONE bit of on-disk state is the buyer's short onboarding session
token (see `state.py`) — needed because the agent drives the flow across separate
CLI invocations.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

# Production control plane. Override with VESTA_CONTROL_URL for staging/testing.
DEFAULT_CONTROL_URL = "https://vesta.run/api"

# Default Claude model for a freshly onboarded agent (the buyer can switch later
# in the app). Anthropic's curated picker is opus / sonnet / haiku.
DEFAULT_MODEL = "sonnet"

# How long the marketing/plan copy quotes; kept here so the CLI and SKILL.md
# agree on the canonical plan ids the checkout endpoint accepts.
PLANS = ("starter", "pro", "power")

# List MONTHLY price (USD) per plan — the NEGOTIATION FLOOR. The agent can quote
# any price >= the floor (uncapped above); the control plane enforces the floor
# server-side, so this is for the agent's UX + a friendly local error. Keep these
# in sync with the control plane's listMonthlyCents().
PLAN_FLOOR_USD = {"starter": 12, "pro": 24, "power": 48}

# Personality presets shipped by the `personality` skill (presets/<name>.md).
# Listed here so `onboard presets` works even if that skill isn't installed yet.
PERSONALITY_PRESETS = ("chill", "classic", "dry", "extra", "polished", "terse")

# Public marketing + install links surfaced by `onboard links`.
LINKS = {
    "marketing": "https://vesta.run",
    "dashboard": "https://vesta.run/dashboard",
    "download": "https://vesta.run/download",
    "ios": "https://vesta.run/download#ios",
    "android": "https://vesta.run/download#android",
    "desktop": "https://vesta.run/download#desktop",
    "terms": "https://vesta.run/legal/terms",
    "privacy": "https://vesta.run/legal/privacy",
}


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration (env-driven)."""

    base_url: str
    referral_code: str | None
    invite_credential: str | None

    @classmethod
    def load(cls) -> Config:
        base = os.environ.get("VESTA_CONTROL_URL", DEFAULT_CONTROL_URL).rstrip("/")
        # Non-secret per-server attribution id; absent on self-hosted boxes.
        ref = os.environ.get("VESTA_REFERRAL_CODE", "").strip() or None
        # The SECRET that mints invites (the gate for invite-only): the referring
        # vesta's per-VM api_key, or the operator admin secret. The data plane must
        # inject one of these into the agent's env for in-chat invite minting; the
        # operator can otherwise hand a pre-minted invite via --invite.
        cred = os.environ.get("VESTA_API_KEY", "").strip() or os.environ.get("VESTA_ADMIN_SECRET", "").strip() or None
        return cls(base_url=base, referral_code=ref, invite_credential=cred)

    @property
    def apex_host(self) -> str:
        """The apex host the control plane lives under, e.g. ``vesta.run``."""
        return urlparse(self.base_url).netloc or "vesta.run"

    def tenant_base(self, subdomain: str) -> str:
        """Base URL of a buyer's own vestad, ``https://<subdomain>.<apex>``."""
        return f"https://{subdomain}.{self.apex_host}"
