"""Configuration for the account CLI.

Everything is read from the environment the agent container already has:

* the control-plane base URL (`https://vesta.run/api`, override with
  `VESTA_CONTROL_URL`);
* how to reach **this box's vestad** over the loopback — `VESTAD_PORT` +
  `AGENT_NAME` + `AGENT_TOKEN` (the same agent-token tier the voice / app-chat
  skills use). The CLI calls vestad to mint a server-identity token; it never
  holds the box's `api_key`.

There is NO on-disk state: every command mints a fresh short-lived token.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Production control plane. Override with VESTA_CONTROL_URL for staging/testing.
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
        control = os.environ.get("VESTA_CONTROL_URL", DEFAULT_CONTROL_URL).rstrip("/")
        # vestad listens on the loopback with a self-signed cert (see the voice /
        # app-chat skills); the agent reaches it at https://localhost:<port>.
        port = os.environ.get("VESTAD_PORT", "").strip()
        vestad_base = f"https://localhost:{port}" if port else ""
        return cls(
            control_url=control,
            vestad_base=vestad_base,
            agent_name=os.environ.get("AGENT_NAME", "").strip(),
            agent_token=os.environ.get("AGENT_TOKEN", "").strip() or None,
        )
