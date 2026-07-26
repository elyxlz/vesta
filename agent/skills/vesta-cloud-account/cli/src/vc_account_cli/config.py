"""Configuration for the account CLI.

Everything is read from the environment the agent container already has:

* the control-plane base URL (`https://vesta.run/api`, override with
  `VESTA_CLOUD_CONTROL_URL`);
* how to reach **this box's vestad** — `VESTAD_HOST` + `VESTAD_PORT` +
  `AGENT_NAME` + `AGENT_TOKEN` (the same agent-token tier the voice / app-chat
  skills use). The CLI calls vestad to mint a server-identity token; it never
  holds the box's `api_key`.

There is NO on-disk state: every command mints a fresh short-lived token.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Production control plane. Override with VESTA_CLOUD_CONTROL_URL for staging/testing.
DEFAULT_CONTROL_URL = "https://vesta.run/api"


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration (env-driven)."""

    control_url: str
    vestad_base: str
    agent_name: str
    agent_token: str | None

    @classmethod
    def load(cls) -> Config:
        control = os.environ.get("VESTA_CLOUD_CONTROL_URL", DEFAULT_CONTROL_URL).rstrip("/")
        # vestad runs natively on the host, never in a container, so VESTAD_HOST
        # (from /run/vestad-env) is how the agent reaches it, not localhost. Missing
        # either half leaves vestad_base empty, tripping the same "not running inside
        # an agent container" check mint_token() already does for a missing port.
        port = os.environ.get("VESTAD_PORT", "").strip()
        host = os.environ.get("VESTAD_HOST", "").strip()
        vestad_base = f"https://{host}:{port}" if port and host else ""
        return cls(
            control_url=control,
            vestad_base=vestad_base,
            agent_name=os.environ.get("AGENT_NAME", "").strip(),
            agent_token=os.environ.get("AGENT_TOKEN", "").strip() or None,
        )
