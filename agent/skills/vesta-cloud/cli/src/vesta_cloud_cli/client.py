"""HTTP client for the account flow.

Two hops, both authenticated WITHOUT any standing secret reaching the agent:

* **vestad** (`https://<BOX_HOST>:<VESTAD_PORT>`, agent-token authed): mint a
  short-lived server-identity token. vestad signs it locally with the box's
  `api_key` — a pure crypto operation, no network call — and hands it back.

* **Control plane** (`https://vesta.run/api`, Bearer = that token): read the
  plan (`GET /account`) or open a billing portal (`POST /account/portal`). The
  token proves "I am this server"; it expires in minutes and is scoped to this
  box's account.
"""

from __future__ import annotations

import warnings
from typing import Any

import requests
from urllib3.exceptions import InsecureRequestWarning

from .config import Config

_TIMEOUT = 20

# vestad serves a self-signed cert on the loopback; the agent reaches it from
# inside the same box, so TLS verification adds nothing and would just fail.
warnings.simplefilter("ignore", InsecureRequestWarning)


class AccountError(Exception):
    """A control-plane / vestad call failed (network, HTTP, or structured error)."""


class Client:
    def __init__(self, config: Config) -> None:
        self._cfg = config

    # --- vestad: mint the server-identity token ------------------------------

    def account_token(self) -> dict[str, Any]:
        """POST <vestad>/agents/<name>/account-token -> {token, expires_in} OR {error}.

        Agent-token authenticated. Returns the response body either way: a box with no
        Vesta Cloud account answers 404 `{error}` (a REACHED vestad refusing to mint),
        which `whoami` reads as "no account" rather than an outage. Raises AccountError
        only on a genuine transport / 5xx failure (vestad unreachable). A missing agent
        identity is reported as an `{error}` body, not raised, for the same reason.

        The minted token is a general server-identity credential the control plane honors
        on any server-scoped route, so one token serves /account, integrations, etc.
        """
        cfg = self._cfg
        if not cfg.vestad_base or not cfg.agent_name or not cfg.agent_token:
            return {"error": "not running inside an agent container (no VESTAD_PORT/BOX_HOST/AGENT_NAME/AGENT_TOKEN)"}
        url = f"{cfg.vestad_base}/agents/{cfg.agent_name}/account-token"
        return self._json(self._send("POST", url, headers={"X-Agent-Token": cfg.agent_token}, json={}, verify=False))

    def mint_token_detail(self) -> dict[str, Any]:
        """{@link account_token} but raises AccountError when no token was minted, for the
        commands (`token`, `plan`, `manage`, `referral`) that need a hard failure."""
        data = self.account_token()
        if not data.get("token"):
            raise AccountError(data.get("error") or "vestad did not return a server-identity token")
        return data

    def mint_token(self) -> str:
        """A server-identity token; see {@link mint_token_detail}."""
        return self.mint_token_detail()["token"]

    # --- control plane: read plan / open portal ------------------------------

    def plan(self, token: str) -> dict[str, Any]:
        """GET /account -> {plan, status, price_cents, subscription_status, renews_at, ...}."""
        return self._json(self._send("GET", f"{self._cfg.control_url}/account", headers=self._auth(token)))

    def portal(self, token: str) -> dict[str, Any]:
        """POST /account/portal -> {url} — a Stripe-hosted manage/upgrade/cancel link."""
        return self._json(self._send("POST", f"{self._cfg.control_url}/account/portal", headers=self._auth(token), json={}))

    # --- low-level helpers ---------------------------------------------------

    @staticmethod
    def _auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _send(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        verify: bool = True,
    ) -> requests.Response:
        try:
            return requests.request(method, url, headers=headers, json=json, timeout=_TIMEOUT, verify=verify)
        except requests.RequestException as e:
            raise AccountError(f"could not reach {url}: {e}") from e

    @staticmethod
    def _json(resp: requests.Response) -> dict[str, Any]:
        try:
            data = resp.json()
        except ValueError:
            raise AccountError(f"non-JSON response ({resp.status_code}): {resp.text[:200]}") from None
        # 4xx bodies carry a structured {error} the skill surfaces verbatim
        # (e.g. "no_billing_account", "not a cloud-managed server"); only a 5xx is
        # an opaque failure worth raising.
        if resp.status_code >= 500:
            raise AccountError(f"server error {resp.status_code}: {data}")
        if not isinstance(data, dict):
            return {"result": data}
        return data
