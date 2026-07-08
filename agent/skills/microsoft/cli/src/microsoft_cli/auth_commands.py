"""Authentication commands for Microsoft CLI."""

import json
import subprocess

from . import auth, owa_rest
from .config import Config, OWA_REST_SCOPES
from .settings import OWA_REST_CLIENT_ID

# JS that extracts the OWA access token from the browser's MSAL storage.
# Returns the token secret (a JWT) or the string 'NONE'.
_OWA_TOKEN_JS = """
(() => {
  for (const store of [localStorage, sessionStorage]) {
    for (let i = 0; i < store.length; i++) {
      const k = store.key(i);
      if (/accesstoken/i.test(k)) {
        try {
          const v = JSON.parse(store.getItem(k));
          if ((v.target || '').includes('outlook.office.com')) return v.secret;
        } catch (e) {}
      }
    }
  }
  return 'NONE';
})()
""".strip()


def list_accounts(config: Config) -> list[dict[str, str]]:
    return [{"email": acc.username, "account_id": acc.account_id} for acc in auth.list_accounts(config.cache_file)]


def remove_account(config: Config, *, account_email: str) -> dict[str, str]:
    app = auth.get_app(config.cache_file)
    email_lower = account_email.lower()
    matches = [a for a in app.get_accounts() if (a["username"] if "username" in a else "").lower() == email_lower]
    if not matches:
        raise ValueError(f"No account found with email '{account_email}'")

    for account in matches:
        app.remove_account(account)

    cache = app.token_cache
    if isinstance(cache, auth.msal.SerializableTokenCache) and cache.has_state_changed:
        auth._write_cache(config.cache_file, content=cache.serialize())

    return {"status": "removed", "email": account_email}


def authenticate_account(config: Config) -> dict[str, str]:
    app = auth.get_app(config.cache_file)
    flow = app.initiate_device_flow(scopes=config.scopes)

    if "user_code" not in flow:
        error_msg = flow["error_description"] if "error_description" in flow else "Unknown error"
        raise Exception(f"Failed to get device code: {error_msg}")

    verification_url = (
        flow["verification_uri"]
        if "verification_uri" in flow
        else (flow["verification_url"] if "verification_url" in flow else "https://microsoft.com/devicelogin")
    )

    return {
        "status": "authentication_required",
        "instructions": "To authenticate a new Microsoft account:",
        "step1": f"Visit: {verification_url}",
        "step2": f"Enter code: {flow['user_code']}",
        "step3": "Sign in with the Microsoft account you want to add",
        "step4": "After authenticating, use 'microsoft auth complete' to finish",
        "device_code": flow["user_code"],
        "verification_url": verification_url,
        "expires_in": flow["expires_in"] if "expires_in" in flow else 900,
        "_flow_cache": json.dumps(flow),
    }


def complete_authentication(config: Config, *, flow_cache: str) -> dict[str, str]:
    try:
        flow = json.loads(flow_cache)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("Invalid flow cache data")

    app = auth.get_app(config.cache_file)
    result = app.acquire_token_by_device_flow(flow)

    if "error" in result:
        error_msg = result["error_description"] if "error_description" in result else result["error"]
        if "authorization_pending" in error_msg:
            return {
                "status": "pending",
                "message": "Authentication is still pending.",
            }
        raise Exception(f"Authentication failed: {error_msg}")

    cache = app.token_cache
    if isinstance(cache, auth.msal.SerializableTokenCache) and cache.has_state_changed:
        auth._write_cache(config.cache_file, content=cache.serialize())

    accounts = app.get_accounts()
    if accounts:
        for account in accounts:
            claims = result["id_token_claims"] if "id_token_claims" in result else {}
            if (account["username"] if "username" in account else "").lower() == (
                claims["preferred_username"] if "preferred_username" in claims else ""
            ).lower():
                return {
                    "status": "success",
                    "username": account["username"],
                    "account_id": account["home_account_id"],
                    "message": f"Successfully authenticated {account['username']}",
                }
        account = accounts[-1]
        return {
            "status": "success",
            "username": account["username"],
            "account_id": account["home_account_id"],
            "message": f"Successfully authenticated {account['username']}",
        }

    return {"status": "error", "message": "Authentication succeeded but no account was found"}


def owa_login(config: Config, *, account_email: str, use_device: bool = False) -> dict[str, str]:
    """Authorize the OWA REST fallback for an account.

    Default (browser): capture the OWA token from the agent's browser session. The tenants
    that need this fallback usually block Graph *and* device-code flow, and browser capture
    works on all of them. It is agent-driven and non-blocking: the agent opens Outlook on the
    web and signs in via the `browser` skill (screenshots + credentials/MFA relayed in chat),
    then this command captures the token from the live session. Runs on the agent's machine,
    so nothing is required of the user's machine.

    `--device`: a device-code sign-in instead (enter a code at a URL, no browser), for the
    subset of locked tenants that still permit device flow. MSAL then auto-refreshes it."""
    if not use_device:
        return _owa_login_browser(config, account_email=account_email)

    app = auth.get_app(config.cache_file, OWA_REST_CLIENT_ID)
    flow = app.initiate_device_flow(scopes=OWA_REST_SCOPES)
    if "user_code" not in flow:
        error_msg = flow["error_description"] if "error_description" in flow else "Unknown error"
        raise Exception(f"Failed to get device code: {error_msg}")

    verification_url = (
        flow["verification_uri"]
        if "verification_uri" in flow
        else (flow["verification_url"] if "verification_url" in flow else "https://microsoft.com/devicelogin")
    )
    return {
        "status": "authentication_required",
        "instructions": "To authorize the OWA REST fallback (no browser needed):",
        "step1": f"Visit: {verification_url}",
        "step2": f"Enter code: {flow['user_code']}",
        "step3": f"Sign in as {account_email}",
        "step4": "Then finish with: microsoft auth owa-complete",
        "device_code": flow["user_code"],
        "verification_url": verification_url,
        "expires_in": flow["expires_in"] if "expires_in" in flow else 900,
        "_flow_cache": json.dumps(flow),
    }


def owa_complete(config: Config, *, account_email: str, flow_cache: str) -> dict[str, str]:
    try:
        flow = json.loads(flow_cache)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("Invalid flow cache data")

    app = auth.get_app(config.cache_file, OWA_REST_CLIENT_ID)
    result = app.acquire_token_by_device_flow(flow)

    if "error" in result:
        error_msg = result["error_description"] if "error_description" in result else result["error"]
        if "authorization_pending" in error_msg:
            return {"status": "pending", "message": "Authorization is still pending."}
        raise Exception(f"OWA REST authorization failed: {error_msg}")

    cache = app.token_cache
    if isinstance(cache, auth.msal.SerializableTokenCache) and cache.has_state_changed:
        auth._write_cache(config.cache_file, content=cache.serialize())

    claims = result["id_token_claims"] if "id_token_claims" in result else {}
    username = (claims["preferred_username"] if "preferred_username" in claims else "") or account_email
    owa_rest.mark_device_account(username, config)
    return {
        "status": "success",
        "account": username,
        "message": f"OWA REST fallback authorized for {username}. Tokens auto-refresh; no re-auth or browser needed.",
    }


def _owa_login_browser(config: Config, *, account_email: str) -> dict[str, str]:
    """Capture the OWA token from the agent's browser session, non-blocking.

    Opens Outlook on the web in the agent's browser and reads the outlook.office.com access
    token from its storage. If the session is not signed in yet, returns `sign_in_required`
    (no blocking prompt) so the agent can drive the sign-in via the `browser` skill and re-run.
    Requires the `browser` skill daemon with DISPLAY=:99."""
    import os

    env = dict(os.environ)
    if "DISPLAY" not in env:
        env["DISPLAY"] = ":99"

    def _run(*args: str) -> str:
        result = subprocess.run(["browser", *args], capture_output=True, text=True, env=env)
        return result.stdout.strip()

    _run("launch", "--stealth")
    _run("open", "https://outlook.office.com/mail/")
    token = _run("evaluate", _OWA_TOKEN_JS)

    if not token or token == "NONE":
        return {
            "status": "sign_in_required",
            "account": account_email,
            "url": "https://outlook.office.com/mail/",
            "message": (
                f"Outlook on the web is open in the browser but not signed in as {account_email}. "
                "Drive the sign-in with the `browser` skill (navigate, enter credentials, handle MFA), "
                "then run `microsoft auth owa-login` again to capture the token."
            ),
        }

    try:
        expires_at = owa_rest.jwt_exp(token)
    except Exception:
        return {"status": "error", "message": "Token was captured but its expiry could not be decoded. The token may be malformed."}

    owa_rest.save_token(account_email, config, token=token, expires_at=expires_at, source="browser")

    return {
        "status": "success",
        "account": account_email,
        "message": f"OWA REST token captured for {account_email}. Valid ~24 h; re-run this command to refresh when it expires.",
    }
