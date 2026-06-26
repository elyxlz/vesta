"""HTTP client for the onboard flow.

Two tiers of calls:

* **Control plane** (`https://vesta.run/api`, Better Auth + onboarding):
  send/verify the buyer's email OTP (which yields THE buyer's own session token),
  reserve-and-checkout, read their server (`/me`), and mint a short-lived,
  server-scoped vestad token (`/server-token`). Everything after the OTP is
  authorized by the buyer's session — the conduit model — never a cross-tenant
  credential, and the per-VM api_key never leaves the control plane.

* **The buyer's vestad** (`https://<subdomain>.vesta.run`, Bearer = the minted
  server-token): create their first agent and connect their Claude account via
  vestad's standalone PKCE OAuth (the code_verifier stays on their box, so the
  code they read back is useless to anyone else).
"""

from __future__ import annotations

import warnings
from typing import Any

import requests
from urllib3.exceptions import InsecureRequestWarning

from .config import Config

_TIMEOUT = 20
# Creating an agent pulls/builds the container image — can take a couple minutes.
_CREATE_TIMEOUT = 300

# vestad serves a self-signed cert on the loopback; we reach it from inside the
# same box, so TLS verification adds nothing and would just fail.
warnings.simplefilter("ignore", InsecureRequestWarning)


class OnboardError(Exception):
    """A control-plane / vestad call failed (network, HTTP, or structured error)."""


class Client:
    def __init__(self, config: Config) -> None:
        self._cfg = config

    def _url(self, path: str) -> str:
        return f"{self._cfg.base_url}{path}"

    # --- vestad: mint THIS (introducing) vesta's server-identity token -------

    def mint_identity_token(self) -> str:
        """POST <vestad>/agents/<name>/account-token -> our server-identity token.

        Agent-token authed; vestad signs it locally with the box's `api_key` (a
        pure crypto op, no network). Only a cloud-managed (hosted) box can mint
        one, so this doubles as the invite-only gate: a self-hosted box (no
        VESTAD_PORT / AGENT_TOKEN) can't mint a token, so it can't walk anyone in.
        """
        cfg = self._cfg
        if not cfg.vestad_base or not cfg.agent_name:
            raise OnboardError("not running inside an agent container (no VESTAD_PORT/AGENT_NAME) — only a hosted vesta can onboard")
        if not cfg.agent_token:
            raise OnboardError("missing AGENT_TOKEN — cannot authenticate to vestad")
        url = f"{cfg.vestad_base}/agents/{cfg.agent_name}/account-token"
        data = self._json(self._send("POST", url, headers={"X-Agent-Token": cfg.agent_token}, json={}, verify=False))
        token = data.get("token")
        if not token:
            # A non-cloud-managed box answers 404 {error}; surface it verbatim.
            raise OnboardError(data.get("error") or "vestad did not return a server-identity token")
        return token

    # --- vestad: read-only reference data over the loopback ------------------

    def _vestad_get(self, path: str) -> Any:
        """GET a public reference endpoint on THIS box's vestad. The onboard skill is just
        another frontend, so it reads personalities / models / defaults from vestad rather
        than keeping its own copies."""
        cfg = self._cfg
        if not cfg.vestad_base:
            raise OnboardError("not running inside an agent container (no VESTAD_PORT) — only a hosted vesta can onboard")
        resp = self._send("GET", f"{cfg.vestad_base}{path}", verify=False)
        if resp.status_code >= 400:
            raise OnboardError(f"vestad {path} -> {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError:
            raise OnboardError(f"vestad {path} returned non-JSON ({resp.status_code})") from None

    def fetch_manifest(self) -> dict[str, Any]:
        return self._vestad_get("/manifest")

    def fetch_agent_defaults(self) -> dict[str, Any]:
        # Read straight from the manifest, the single source of these defaults (the default provider's
        # default model + the default personality). A missing key is a real error, not a silent default.
        manifest = self.fetch_manifest()
        provider = manifest["providers"][manifest["default_provider"]]
        return {"model": provider["default_model"], "personality": manifest["default_personality"]}

    def fetch_personalities(self) -> list[dict[str, Any]]:
        # The personality catalog the manifest carries (merged from the skill presets by vestad).
        return self.fetch_manifest()["personalities"]

    def fetch_claude_models(self) -> list[dict[str, Any]]:
        # Claude's model catalog lives in the manifest (slugs); shape them as {id} for the picker.
        return [{"id": slug} for slug in self.fetch_manifest()["providers"]["claude"]["models"]]

    # --- control plane: account pre-create (authed as THIS vesta) ------------

    def create_account(self, email: str, identity_token: str) -> dict[str, Any]:
        """POST /onboard/account -> {created, email}.

        Pre-creates the invitee's account so the control plane will send them a
        code (web signup is disabled — invite-only). Bearer is our server-identity
        token. Idempotent: an existing email returns {created: false}. A 4xx body
        carries a structured {error} (e.g. our vesta isn't active) to surface.
        """
        return self._json(self._post("/onboard/account", json={"email": email}, headers=self._auth(identity_token)))

    # --- control plane: auth -------------------------------------------------

    def send_otp(self, email: str) -> dict[str, Any]:
        """POST /auth/email-otp/send-verification-otp — email the buyer a code."""
        resp = self._post(
            "/auth/email-otp/send-verification-otp",
            json={"email": email, "type": "sign-in"},
        )
        return self._json(resp)

    def verify_otp(self, email: str, code: str) -> str | None:
        """POST /auth/sign-in/email-otp — verify the code, return THE buyer's token.

        Returns None when the code is wrong/expired (Better Auth answers 4xx with
        `{message: "INVALID_OTP", ...}`, no token) so the CLI can surface a friendly
        'wrong code' rather than treating it as the control plane being unreachable.
        Better Auth's `bearer` plugin returns the session token in the
        `set-auth-token` response header (falling back to the body `token`).
        """
        resp = self._post(
            "/auth/sign-in/email-otp",
            json={"email": email, "otp": code},
        )
        if 400 <= resp.status_code < 500:
            return None  # invalid/expired code — a normal, surfaced outcome
        data = self._json(resp)  # raises on 5xx (real transport/server failure)
        return resp.headers.get("set-auth-token") or data.get("token")

    # --- control plane: onboarding (authed as the buyer) ---------------------

    def checkout(
        self,
        *,
        token: str,
        plan: str,
        referral_code: str | None,
        price: float | None,
        code: str | None,
    ) -> dict[str, Any]:
        """POST /onboard/checkout -> {url, subdomain, server_id}. Auto-assigns the subdomain."""
        body: dict[str, Any] = {"plan": plan}
        if price is not None:
            body["price"] = price  # negotiated monthly USD; floor enforced server-side
        if code:
            body["code"] = code  # discount code; unknown -> {"error": "invalid code"}
        headers = self._auth(token)
        if referral_code:
            headers["X-Vesta-Referral"] = referral_code
        return self._json(self._post("/onboard/checkout", json=body, headers=headers))

    def me(self, token: str) -> dict[str, Any]:
        """GET /me -> {user, server}. `server` is null until checkout reserves one."""
        return self._json(self._get("/me", headers=self._auth(token)))

    def server_token(self, token: str, server_id: str) -> str:
        """GET /server-token?server_id= -> a short-lived vestad access token."""
        data = self._json(
            self._get(
                "/server-token",
                params={"server_id": server_id},
                headers=self._auth(token),
            )
        )
        access = data.get("access_token")
        if not access:
            raise OnboardError("control plane did not return a server token")
        return access

    # --- the buyer's vestad (Bearer = minted server-token) -------------------

    def create_agent(self, *, subdomain: str, server_token: str, name: str) -> dict[str, Any]:
        """POST <tenant>/agents — create the buyer's first (empty) agent. Personality and the
        freeform seed context are delivered later, once the agent is up, through set_provider's
        config field (the agent owns its config store; vestad no longer accepts them at create)."""
        url = f"{self._cfg.tenant_base(subdomain)}/agents"
        return self._json(self._raw_post(url, json={"name": name}, token=server_token, timeout=_CREATE_TIMEOUT))

    def claude_oauth_start(self, *, subdomain: str, server_token: str) -> dict[str, Any]:
        """POST <tenant>/providers/claude/oauth/start -> {auth_url, session_id}."""
        url = f"{self._cfg.tenant_base(subdomain)}/providers/claude/oauth/start"
        return self._json(self._raw_post(url, json={}, token=server_token))

    def claude_oauth_complete(self, *, subdomain: str, server_token: str, session_id: str, code: str) -> str:
        """POST <tenant>/providers/claude/oauth/complete -> the credentials blob."""
        url = f"{self._cfg.tenant_base(subdomain)}/providers/claude/oauth/complete"
        data = self._json(self._raw_post(url, json={"session_id": session_id, "code": code}, token=server_token))
        creds = data.get("credentials")
        if not creds:
            raise OnboardError("OAuth completion returned no credentials")
        return creds

    def set_provider(
        self,
        *,
        subdomain: str,
        server_token: str,
        name: str,
        credentials: str,
        model: str | None,
        personality: str | None = None,
        seed_context: str | None = None,
    ) -> dict[str, Any]:
        """Provision the agent: sign in the Claude provider (PUT /provider, model folded in) and write
        its preferences (PUT /config), then restart once so it wakes with everything in place. Writes
        don't restart on their own, so this is several writes + a single restart."""
        base = self._cfg.tenant_base(subdomain)
        provider: dict[str, Any] = {"kind": "claude", "credentials": credentials}
        if model:
            provider["model"] = model
        self._json(self._raw_put(f"{base}/agents/{name}/provider", json=provider, token=server_token, timeout=120))
        prefs: dict[str, Any] = {}
        if personality:
            prefs["agent_personality"] = personality
        if seed_context:
            prefs["seed_context"] = seed_context
        if prefs:
            self._json(self._raw_put(f"{base}/agents/{name}/config", json=prefs, token=server_token, timeout=120))
        return self._json(self._raw_post(f"{base}/agents/{name}/restart", json={}, token=server_token, timeout=120))

    # --- low-level helpers ---------------------------------------------------

    @staticmethod
    def _auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        return self._send("GET", self._url(path), params=params, headers=headers)

    def _post(
        self,
        path: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        return self._send("POST", self._url(path), json=json, headers=headers)

    def _raw_post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        token: str,
        timeout: int = _TIMEOUT,
    ) -> requests.Response:
        return self._send("POST", url, json=json, headers=self._auth(token), timeout=timeout)

    def _raw_put(
        self,
        url: str,
        *,
        json: dict[str, Any],
        token: str,
        timeout: int = _TIMEOUT,
    ) -> requests.Response:
        return self._send("PUT", url, json=json, headers=self._auth(token), timeout=timeout)

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = _TIMEOUT,
        verify: bool = True,
    ) -> requests.Response:
        try:
            return requests.request(method, url, params=params, json=json, headers=headers, timeout=timeout, verify=verify)
        except requests.RequestException as e:
            raise OnboardError(f"could not reach {url}: {e}") from e

    @staticmethod
    def _json(resp: requests.Response) -> dict[str, Any]:
        try:
            data = resp.json()
        except ValueError:
            raise OnboardError(f"non-JSON response ({resp.status_code}): {resp.text[:200]}") from None
        # 4xx bodies carry a structured {error} the skill should surface verbatim
        # (e.g. "rate limited", "invalid code", "already provisioned"); only a 5xx
        # is an opaque failure worth raising.
        if resp.status_code >= 500:
            raise OnboardError(f"server error {resp.status_code}: {data}")
        if not isinstance(data, dict):
            return {"result": data}
        return data
