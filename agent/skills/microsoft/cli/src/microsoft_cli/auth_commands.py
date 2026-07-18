"""Authentication commands for Microsoft CLI."""

import json
import subprocess

from . import auth, capture, owa_rest, teams
from .config import DEFAULT_CLIENT_SCOPES, OWA_REST_SCOPES, Config
from .settings import DEFAULT_CLIENT_ID, OWA_REST_CLIENT_ID

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

# One-liner for the user's own Teams browser console; copies the graph.microsoft.com token with the
# most Teams scopes to their clipboard for `microsoft auth teams-capture --token <TOKEN>` (a session
# can hold several graph tokens; the fullest-scoped one is the Teams app's).
TEAMS_TOKEN_SNIPPET = (
    "copy((()=>{const w=['Chat.','ChannelMessage.','Channel.','Team.','Presence.'];let b=null,bs=-1;"
    "for(const s of[localStorage,sessionStorage])for(let i=0;i<s.length;i++){const k=s.key(i);"
    "if(!/accesstoken/i.test(k))continue;try{const v=JSON.parse(s.getItem(k));const t=v.target||'';"
    "if(!t.includes('graph.microsoft.com'))continue;const sc=w.reduce((n,x)=>n+(t.includes(x)?1:0),0);"
    "if(sc>bs){bs=sc;b=v.secret;}}catch(e){}}return b||'NONE';})())"
)


# AADSTS codes and phrases a locked work/school tenant returns when it blocks the default
# public client: the device-flow path is walled and the caller must switch to browser capture.
_CONSENT_WALL_MARKERS = ("aadsts65001", "aadsts90094", "aadsts900", "admin", "consent", "not authorized")


def _is_consent_wall(error_msg: str) -> bool:
    lowered = error_msg.lower()
    return any(marker in lowered for marker in _CONSENT_WALL_MARKERS)


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
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError("Invalid flow cache data") from e

    app = auth.get_app(config.cache_file)
    result = app.acquire_token_by_device_flow(flow)

    if "error" in result:
        error_msg = result["error_description"] if "error_description" in result else result["error"]
        if "authorization_pending" in error_msg:
            return {
                "status": "pending",
                "message": "Authentication is still pending.",
            }
        if _is_consent_wall(error_msg):
            return {
                "status": "admin_consent_required",
                "message": (
                    "This is a locked work/school tenant: it blocks the default app, so device-code sign-in needs an admin. "
                    "Use the browser-capture fallback instead (no admin consent needed): `microsoft auth owa-login --account <email>` "
                    "for mail/calendar, and `microsoft auth teams-capture --account <email>` for Teams. Then pass `--backend owa-rest`."
                ),
                "detail": error_msg,
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
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError("Invalid flow cache data") from e

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
            "message": (
                "That does not look like an OWA access token (its expiry could not be decoded). "
                "Re-copy the value the snippet put on the clipboard."
            ),
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
        result = subprocess.run(["browser", *args], capture_output=True, text=True, env=env, check=False)
        return result.stdout.strip()

    _run("launch")
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
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError("Invalid flow cache data") from e

    app = auth.get_app(config.cache_file, DEFAULT_CLIENT_ID)
    result = app.acquire_token_by_device_flow(flow)

    if "error" in result:
        error_msg = result["error_description"] if "error_description" in result else result["error"]
        if "authorization_pending" in error_msg:
            return {"status": "pending", "message": "Authorization is still pending."}
        if _is_consent_wall(error_msg):
            return {
                "status": "admin_consent_required",
                "message": (
                    "This is a locked work/school tenant: device-code Teams sign-in needs an admin. Capture a token from Teams "
                    "on the web instead (no admin consent needed): `microsoft auth teams-capture --account <email>`, "
                    "then use `--backend owa-rest`."
                ),
                "detail": error_msg,
            }
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
            "message": (
                "That does not look like a Teams access token (its expiry could not be decoded). "
                "Re-copy the value the snippet put on the clipboard."
            ),
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
        result = subprocess.run(["browser", *args], capture_output=True, text=True, env=env, check=False)
        return result.stdout.strip()

    _run("launch")
    _run("open", "https://teams.microsoft.com/")
    token = _run("evaluate", capture._TEAMS_TOKEN_JS)

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


# ---------------------------------------------------------------------------
# Unified onboarding: one command sets up mail, calendar, and Teams together.
# ---------------------------------------------------------------------------

# Device-code setup consents mail + calendar + Teams in one sign-in, so a personal or permissive
# tenant is fully provisioned by a single code. Locked tenants fall through to the browser capture.
_SETUP_SCOPES = [*DEFAULT_CLIENT_SCOPES, *teams.TEAMS_SCOPES]

# Personal Microsoft consumer domains. Everything else is treated as a work/school (custom-domain)
# account, whose tenant usually blocks the default public client, so we default those to the browser
# handover instead of wasting a device-code round-trip that the tenant will reject.
_PERSONAL_MS_DOMAINS = {"outlook.com", "hotmail.com", "live.com", "msn.com", "passport.com", "windowslive.com"}


def _is_personal_ms_account(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower().strip()
    if domain in _PERSONAL_MS_DOMAINS:
        return True
    # Country variants: outlook.fr, hotmail.co.uk, live.de, etc.
    first = domain.split(".")[0]
    return first in {"outlook", "hotmail", "live"}


def _setup_save_captured(config: Config, *, account_email: str, captured: dict) -> dict[str, str]:
    """Persist browser-captured tokens (mail over OWA REST, Teams over Graph) and summarize."""
    got = capture.save_captured(config, account_email, captured)
    return {
        "status": "success",
        "account": account_email,
        "provisioned": ", ".join(got) if got else "nothing",
        "backend": "owa-rest",
        "message": (
            f"{account_email} is set up ({', '.join(got)}). The daemon silently refreshes these from the saved "
            "sign-in, so no daily re-login. Use commands normally; `--backend auto` picks this path."
        ),
    }


def _setup_begin_browser(config: Config, *, account_email: str) -> dict[str, str]:
    user_url = capture.begin_interactive(config, account_email)
    return {
        "status": "sign_in",
        "account": account_email,
        "user_url": user_url,
        "message": (
            f"Open {user_url} and sign in as {account_email} (SSO + MFA) in that window. When you land on your "
            f"inbox, finish with: microsoft auth setup --account {account_email} --capture"
        ),
        "next": f"microsoft auth setup --account {account_email} --capture",
    }


def _setup_finish_device(config: Config, *, account_email: str, flow_cache: str) -> dict[str, str]:
    """Finish a device-code `auth setup`; on a consent wall, pivot to the browser capture."""
    try:
        flow = json.loads(flow_cache)
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError("Invalid flow cache data") from e
    app = auth.get_app(config.cache_file, DEFAULT_CLIENT_ID)
    result = app.acquire_token_by_device_flow(flow)
    if "error" in result:
        error_msg = result["error_description"] if "error_description" in result else result["error"]
        if "authorization_pending" in error_msg:
            return {"status": "pending", "message": "Sign-in is still pending; finish the code entry, then retry."}
        if _is_consent_wall(error_msg):
            # Locked tenant: device code is blocked, pivot to the browser capture with no extra ask.
            return _setup_begin_browser(config, account_email=account_email)
        raise Exception(f"Sign-in failed: {error_msg}")
    cache = app.token_cache
    if isinstance(cache, auth.msal.SerializableTokenCache) and cache.has_state_changed:
        auth._write_cache(config.cache_file, content=cache.serialize())
    teams.mark_device_account(account_email, config)
    return {
        "status": "success",
        "account": account_email,
        "provisioned": "mail/calendar, Teams",
        "backend": "graph",
        "message": f"{account_email} is set up over Graph (mail, calendar, Teams). Tokens auto-refresh; no re-auth needed.",
    }


def auth_setup(
    config: Config,
    *,
    account_email: str,
    use_browser: bool = False,
    flow_cache: str | None = None,
    do_capture: bool = False,
    force_device: bool = False,
) -> dict[str, str]:
    """One onboarding flow for mail + calendar + Teams.

    No flags: a work/school (custom-domain) account defaults to the browser handover, since its tenant
    usually blocks the default public client and would reject a device code; a personal Microsoft account
    (outlook.com, hotmail.*, etc.) starts a device-code sign-in (auto-refreshes via MSAL). ``--flow-cache``:
    finish a device-code sign-in; if the tenant walls it, pivot to the browser automatically. ``--browser``:
    force the browser capture (for a known locked tenant). ``--device`` (``force_device``): force device code
    even for a work/school domain (permissive tenants). ``--capture``: after signing in via the browser, lift
    the tokens and finish."""
    if do_capture:
        captured = capture.finish_interactive(config, account_email)
        return _setup_save_captured(config, account_email=account_email, captured=captured)

    if use_browser:
        return _setup_begin_browser(config, account_email=account_email)

    if flow_cache is not None:
        return _setup_finish_device(config, account_email=account_email, flow_cache=flow_cache)

    if not force_device and not _is_personal_ms_account(account_email):
        # Work/school (custom domain): the tenant almost always blocks the public client, so skip the
        # device-code round-trip that would be rejected and hand off to the browser up front.
        return _setup_begin_browser(config, account_email=account_email)

    app = auth.get_app(config.cache_file, DEFAULT_CLIENT_ID)
    flow = app.initiate_device_flow(scopes=_SETUP_SCOPES)
    if "user_code" not in flow:
        error_msg = flow["error_description"] if "error_description" in flow else "Unknown error"
        raise Exception(f"Failed to get device code: {error_msg}")
    verification_url = (
        flow["verification_uri"]
        if "verification_uri" in flow
        else (flow["verification_url"] if "verification_url" in flow else "https://microsoft.com/devicelogin")
    )
    return {
        "status": "device_code",
        "account": account_email,
        "verification_url": verification_url,
        "code": flow["user_code"],
        "message": (
            f"Ask {account_email} to visit {verification_url} and enter code {flow['user_code']}. Then finish with: "
            f"microsoft auth setup --account {account_email} --flow-cache <cache>. If it's a locked work/school "
            f"tenant that rejects the code, rerun with --browser instead."
        ),
        "next": f"microsoft auth setup --account {account_email} --flow-cache <cache>",
        "_flow_cache": json.dumps(flow),
    }
