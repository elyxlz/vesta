"""Authentication commands for Microsoft CLI."""

import json
import subprocess

from . import auth, owa_rest, teams
from .config import Config, OWA_REST_SCOPES
from .settings import OWA_REST_CLIENT_ID, DEFAULT_CLIENT_ID

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

# One-line version to hand the user for their own browser console: it copies the
# outlook.office.com access token to their clipboard (or prints NONE if not signed in).
# They paste it back into `microsoft auth owa-login --token <TOKEN>`, so their password
# and MFA never leave their machine.
OWA_TOKEN_SNIPPET = (
    "copy((()=>{for(const s of[localStorage,sessionStorage])for(let i=0;i<s.length;i++){"
    "const k=s.key(i);if(/accesstoken/i.test(k)){try{const v=JSON.parse(s.getItem(k));"
    "if((v.target||'').includes('outlook.office.com'))return v.secret;}catch(e){}}}return 'NONE';})())"
)

# JS that extracts a graph.microsoft.com access token from Teams' MSAL storage.
# The Teams web client acquires Graph tokens (Chat scopes) for its own calls; this
# grabs one so the same Graph endpoints work on a tenant that blocks the CLI's app.
_TEAMS_TOKEN_JS = """
(() => {
  for (const store of [localStorage, sessionStorage]) {
    for (let i = 0; i < store.length; i++) {
      const k = store.key(i);
      if (/accesstoken/i.test(k)) {
        try {
          const v = JSON.parse(store.getItem(k));
          if ((v.target || '').includes('graph.microsoft.com')) return v.secret;
        } catch (e) {}
      }
    }
  }
  return 'NONE';
})()
""".strip()

# One-liner for the user's own Teams browser console; copies a graph.microsoft.com
# token to their clipboard for `microsoft auth teams-capture --token <TOKEN>`.
TEAMS_TOKEN_SNIPPET = (
    "copy((()=>{for(const s of[localStorage,sessionStorage])for(let i=0;i<s.length;i++){"
    "const k=s.key(i);if(/accesstoken/i.test(k)){try{const v=JSON.parse(s.getItem(k));"
    "if((v.target||'').includes('graph.microsoft.com'))return v.secret;}catch(e){}}}return 'NONE';})())"
)


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


def owa_login(config: Config, *, account_email: str, use_device: bool = False, token: str | None = None) -> dict[str, str]:
    """Authorize the OWA REST fallback for an account.

    `--token <JWT>`: save a token the user extracted from their own signed-in Outlook session
    (run OWA_TOKEN_SNIPPET in their browser console). The user's password and MFA never leave
    their machine, only the resulting bearer token. Best when the agent cannot reach the user's
    browser.

    Default (browser): capture the OWA token from the agent's browser session. The tenants
    that need this fallback usually block Graph *and* device-code flow, and browser capture
    works on all of them. It is agent-driven and non-blocking: the agent opens Outlook on the
    web and signs in via the `browser` skill (screenshots + credentials/MFA relayed in chat),
    then this command captures the token from the live session. Runs on the agent's machine,
    so nothing is required of the user's machine.

    `--device`: a device-code sign-in instead (enter a code at a URL, no browser), for the
    subset of locked tenants that still permit device flow. MSAL then auto-refreshes it."""
    if token:
        return _owa_login_paste(config, account_email=account_email, token=token)
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


def _owa_login_paste(config: Config, *, account_email: str, token: str) -> dict[str, str]:
    token = token.strip()
    try:
        expires_at = owa_rest.jwt_exp(token)
    except Exception:
        return {
            "status": "error",
            "message": "That does not look like an OWA access token (its expiry could not be decoded). Re-copy the value the snippet put on the clipboard.",
        }
    owa_rest.save_token(account_email, config, token=token, expires_at=expires_at, source="browser")
    return {
        "status": "success",
        "account": account_email,
        "message": f"OWA REST token saved for {account_email}. Paste a fresh one (re-run the snippet) when it expires.",
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


def teams_login(config: Config) -> dict[str, str]:
    """Start a device-flow sign-in for the Teams Graph scopes.

    Kept separate from `auth login` so a mail-only account is never prompted to consent to Teams
    scopes; MSAL caches the two scope sets side by side under the same account."""
    app = auth.get_app(config.cache_file, DEFAULT_CLIENT_ID)
    flow = app.initiate_device_flow(scopes=teams.TEAMS_SCOPES)
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
        "instructions": "To authorize Microsoft Teams:",
        "step1": f"Visit: {verification_url}",
        "step2": f"Enter code: {flow['user_code']}",
        "step3": "Sign in with the Microsoft account whose Teams you want to reach",
        "step4": "Then finish with: microsoft auth teams-complete",
        "device_code": flow["user_code"],
        "verification_url": verification_url,
        "expires_in": flow["expires_in"] if "expires_in" in flow else 900,
        "_flow_cache": json.dumps(flow),
    }


def teams_complete(config: Config, *, flow_cache: str) -> dict[str, str]:
    try:
        flow = json.loads(flow_cache)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("Invalid flow cache data")

    app = auth.get_app(config.cache_file, DEFAULT_CLIENT_ID)
    result = app.acquire_token_by_device_flow(flow)

    if "error" in result:
        error_msg = result["error_description"] if "error_description" in result else result["error"]
        if "authorization_pending" in error_msg:
            return {"status": "pending", "message": "Authorization is still pending."}
        raise Exception(f"Teams authorization failed: {error_msg}")

    cache = app.token_cache
    if isinstance(cache, auth.msal.SerializableTokenCache) and cache.has_state_changed:
        auth._write_cache(config.cache_file, content=cache.serialize())

    claims = result["id_token_claims"] if "id_token_claims" in result else {}
    username = claims["preferred_username"] if "preferred_username" in claims else ""
    if not username:
        return {"status": "error", "message": "Teams authorization succeeded but no account was found"}
    teams.mark_device_account(username, config)
    return {
        "status": "success",
        "account": username,
        "message": f"Teams authorized for {username}. Tokens auto-refresh; no re-auth or browser needed.",
    }


def teams_capture(config: Config, *, account_email: str, token: str | None = None) -> dict[str, str]:
    """Capture a Graph Teams token for a locked tenant.

    `--token <JWT>`: save a token the user extracted from their own signed-in Teams session
    (run TEAMS_TOKEN_SNIPPET in their browser console); their password and MFA never leave their
    machine. Otherwise capture it from the agent's own browser session, non-blocking: opens Teams
    on the web and reads the graph.microsoft.com token from its storage, returning
    `sign_in_required` if the session is not signed in yet."""
    if token:
        return _teams_capture_paste(config, account_email=account_email, token=token)
    return _teams_capture_browser(config, account_email=account_email)


def _teams_capture_paste(config: Config, *, account_email: str, token: str) -> dict[str, str]:
    token = token.strip()
    try:
        expires_at = owa_rest.jwt_exp(token)
    except Exception:
        return {
            "status": "error",
            "message": "That does not look like a Teams access token (its expiry could not be decoded). Re-copy the value the snippet put on the clipboard.",
        }
    teams.save_token(account_email, config, token=token, expires_at=expires_at, source="browser")
    return {
        "status": "success",
        "account": account_email,
        "message": f"Teams token saved for {account_email}. Paste a fresh one (re-run the snippet) when it expires.",
    }


def _teams_capture_browser(config: Config, *, account_email: str) -> dict[str, str]:
    import os

    env = dict(os.environ)
    if "DISPLAY" not in env:
        env["DISPLAY"] = ":99"

    def _run(*args: str) -> str:
        result = subprocess.run(["browser", *args], capture_output=True, text=True, env=env)
        return result.stdout.strip()

    _run("launch", "--stealth")
    _run("open", "https://teams.microsoft.com/")
    token = _run("evaluate", _TEAMS_TOKEN_JS)

    if not token or token == "NONE":
        return {
            "status": "sign_in_required",
            "account": account_email,
            "url": "https://teams.microsoft.com/",
            "message": (
                f"Teams on the web is open in the browser but not signed in as {account_email}. "
                "Drive the sign-in with the `browser` skill (navigate, enter credentials, handle MFA), "
                "then run `microsoft auth teams-capture` again to capture the token."
            ),
        }

    try:
        expires_at = owa_rest.jwt_exp(token)
    except Exception:
        return {"status": "error", "message": "Token was captured but its expiry could not be decoded. The token may be malformed."}

    teams.save_token(account_email, config, token=token, expires_at=expires_at, source="browser")
    return {
        "status": "success",
        "account": account_email,
        "message": f"Teams token captured for {account_email}. Valid ~24 h; re-run this command to refresh when it expires.",
    }
