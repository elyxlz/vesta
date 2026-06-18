"""Configuration for the onboard CLI.

Everything is read from the environment:

* the control-plane base URL and (for hosted vestas) the non-secret referral code
  that attributes a completed signup to this account;
* how to reach **this box's vestad** over the loopback (`VESTAD_PORT` +
  `AGENT_NAME` + `AGENT_TOKEN`) so the CLI can mint a server-identity token. That
  token authenticates the account pre-create (`POST /api/onboard/account`) as THIS
  introducing vesta — the invite-only gate. The CLI never holds the box's api_key.

The ONE bit of on-disk state is the buyer's short onboarding session token (see
`state.py`) — needed because the agent drives the flow across separate CLI
invocations.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

# Production control plane. Override with VESTA_CONTROL_URL for staging/testing.
DEFAULT_CONTROL_URL = "https://vesta.run/api"

# Hosted Vesta is ONE plan, one box — the control plane's `pro` tier (4 vCPU /
# 8 GB). The control plane also defines starter/power for admin provisioning and
# upgrades, but onboarding only ever sells this one.
PLAN = "pro"

# List MONTHLY price (USD) — the NEGOTIATION FLOOR. The agent can quote any price
# >= it (uncapped above); the control plane enforces the floor server-side, so
# this is for the agent's UX + a friendly local error. Keep in sync with the
# control plane's listMonthlyCents("pro").
PLAN_FLOOR_USD = 24

# Public marketing + install links surfaced by `onboard links`.
LINKS = {
    "marketing": "https://vesta.run",
    "account": "https://vesta.run/account",
    "download": "https://github.com/elyxlz/vesta/releases/latest",
    "terms": "https://vesta.run/legal/terms",
    "privacy": "https://vesta.run/legal/privacy",
}


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration (env-driven)."""

    base_url: str
    referral_code: str | None
    vestad_base: str
    agent_name: str
    agent_token: str | None

    @classmethod
    def load(cls) -> Config:
        base = os.environ.get("VESTA_CONTROL_URL", DEFAULT_CONTROL_URL).rstrip("/")
        # Non-secret per-server attribution id; absent on self-hosted boxes.
        ref = os.environ.get("VESTA_REFERRAL_CODE", "").strip() or None
        # vestad listens on the loopback with a self-signed cert (see the account /
        # voice skills); the agent reaches it at https://localhost:<port> and mints
        # a server-identity token there to authenticate the account pre-create.
        port = os.environ.get("VESTAD_PORT", "").strip()
        vestad_base = f"https://localhost:{port}" if port else ""
        return cls(
            base_url=base,
            referral_code=ref,
            vestad_base=vestad_base,
            agent_name=os.environ.get("AGENT_NAME", "").strip(),
            agent_token=os.environ.get("AGENT_TOKEN", "").strip() or None,
        )

    @property
    def apex_host(self) -> str:
        """The apex host the control plane lives under, e.g. ``vesta.run``."""
        return urlparse(self.base_url).netloc or "vesta.run"

    def tenant_base(self, subdomain: str) -> str:
        """Base URL of a buyer's own vestad, ``https://<subdomain>.<apex>``."""
        return f"https://{subdomain}.{self.apex_host}"
