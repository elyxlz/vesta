"""Filesystem layout + small config helpers for the stripe-pay skill."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


# OAuth scope for Link Wallet for Agents. Per Stripe's April 2026 docs the
# agent only needs permission to create spend requests on the wallet — caps
# and approvals are enforced by Link itself, not by us. Keep this minimal.
LINK_OAUTH_SCOPE = "link.wallet.charge"

# Stripe's hosted OAuth + token endpoints (per the Agent Toolkit docs).
# Kept here as constants so they can be overridden via env vars for testing.
LINK_OAUTH_AUTHORIZE_URL = os.environ.get(
    "STRIPE_PAY_AUTHORIZE_URL",
    "https://link.stripe.com/oauth/agents/authorize",
)
LINK_OAUTH_TOKEN_URL = os.environ.get(
    "STRIPE_PAY_TOKEN_URL",
    "https://api.stripe.com/v1/oauth/token",
)

# The localhost port the CLI listens on to capture the OAuth redirect.
DEFAULT_CALLBACK_PORT = 53682
DEFAULT_REDIRECT_URI = f"http://127.0.0.1:{DEFAULT_CALLBACK_PORT}/callback"


@dataclass(frozen=True)
class Config:
    """Where stripe-pay reads/writes things on disk."""

    data_dir: Path = Path.home() / ".stripe-pay"

    @property
    def credentials_file(self) -> Path:
        """OAuth refresh + access tokens. chmod 600."""
        return self.data_dir / "credentials.json"

    @property
    def api_key_file(self) -> Path:
        """Restricted Stripe API key, written by the user during setup."""
        return self.data_dir / "api_key"

    @property
    def history_file(self) -> Path:
        """Append-only jsonl log, one entry per charge attempt."""
        return self.data_dir / "history.jsonl"

    @property
    def callback_port(self) -> int:
        return DEFAULT_CALLBACK_PORT

    @property
    def redirect_uri(self) -> str:
        return DEFAULT_REDIRECT_URI

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Restrict the dir itself in case of multi-user systems.
        try:
            self.data_dir.chmod(0o700)
        except OSError:
            pass

    # -- credentials helpers -------------------------------------------------

    def load_credentials(self) -> dict | None:
        """Return the saved OAuth credentials dict, or None if absent."""
        path = self.credentials_file
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def save_credentials(self, payload: dict) -> None:
        """Persist credentials with restrictive perms."""
        self.ensure_dirs()
        path = self.credentials_file
        path.write_text(json.dumps(payload, indent=2))
        path.chmod(0o600)

    def load_api_key(self) -> str | None:
        """Return the restricted API key (rk_...) the user wrote during setup."""
        path = self.api_key_file
        if not path.exists():
            return None
        return path.read_text().strip() or None
