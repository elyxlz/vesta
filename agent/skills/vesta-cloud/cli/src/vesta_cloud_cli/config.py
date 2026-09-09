"""Configuration for the vesta-cloud CLI.

Everything is read from the environment the agent container already has:

* the control-plane base URL (`https://vesta.run/api`, override with
  `VESTA_CLOUD_CONTROL_URL`);
* how to reach **this box's vestad**: `BOX_HOST` + `VESTAD_PORT` +
  `AGENT_NAME` + `AGENT_TOKEN` (the same agent-token tier the voice / chat
  skills use). The CLI calls vestad to mint a server-identity token; it never
  holds the box's `api_key`.

There is NO on-disk credential: every command mints a fresh short-lived token.
(The only file this CLI writes is the referral code, see `referral_store`.)

`VESTA_CLOUD_CONTROL_URL` is only a control-plane URL knob here, NOT the "do I have
an account" signal: cloud-init sets it on managed VMs, but a self-hosted box may hold
a Vesta Cloud account too. Whether an account exists is answered by whether vestad can
mint a server-identity token the control plane honors (`whoami`), never by this var.
`managed_infra` records the var only as the narrower "this VM is Vesta-operated" fact.
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
    managed_infra: bool

    @classmethod
    def load(cls) -> Config:
        cloud_url = os.environ.get("VESTA_CLOUD_CONTROL_URL", "").strip()
        control = (cloud_url or DEFAULT_CONTROL_URL).rstrip("/")
        # vestad runs natively on the host, never in a container, so BOX_HOST
        # (from /run/vestad-env) is how the agent reaches it, not localhost.
        # Missing either half leaves vestad_base empty, tripping Client's
        # "not running inside an agent container" guard (which names all four
        # required vars: VESTAD_PORT/BOX_HOST/AGENT_NAME/AGENT_TOKEN).
        port = os.environ.get("VESTAD_PORT", "").strip()
        host = os.environ.get("BOX_HOST", "").strip()
        vestad_base = f"https://{host}:{port}" if port and host else ""
        return cls(
            control_url=control,
            vestad_base=vestad_base,
            agent_name=os.environ.get("AGENT_NAME", "").strip(),
            agent_token=os.environ.get("AGENT_TOKEN", "").strip() or None,
            managed_infra=bool(cloud_url),
        )
