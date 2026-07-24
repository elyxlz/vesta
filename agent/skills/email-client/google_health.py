#!/usr/bin/env python3
"""Google OAuth client health-probe + self-heal (Gmail accounts only).

The email-client skill rides Thunderbird's PUBLIC verified Google OAuth client.
If that shared client is deleted or rotated upstream (as the previous ...t1glqf
client was), Gmail silently breaks for everyone until someone notices. This
module detects that condition WITHOUT any fresh user interaction and recovers
from it automatically where possible.

How the probe works: it attempts an OAuth token refresh using an account's
already-STORED refresh token and classifies the error. The key distinction is:

    deleted_client / invalid_client / "not found"  ->  the CLIENT is dead
                                                        (swap the client id;
                                                         do NOT bother the user)
    invalid_grant                                   ->  the USER TOKEN is bad
                                                        (re-auth the user; the
                                                         client is fine)

Only a dead client triggers self-heal. On a dead-client detection we re-resolve
Thunderbird's current client from comm-central (via thunderbird_client) and retry
the refresh once with the fresh client. If that still fails we write a clear,
plain-English notification instead of a cryptic OAuth error.

This is strictly Google-specific and gated to Gmail accounts. It never sends mail
and never touches the user's mailbox. EMAIL_DRAFT_ONLY is irrelevant here.
"""

from __future__ import annotations

import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

# Probe outcome classifications.
HEALTHY = "healthy"
DEAD_CLIENT = "dead_client"
BAD_TOKEN = "bad_token"
UNKNOWN = "unknown"
SKIPPED = "skipped"
HEALED = "healed"

DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"

NOTIF_DIR = pathlib.Path.home() / "agent" / "notifications"

# Run the daemon-driven probe at most this often (once a day, not every poll).
PROBE_INTERVAL_SECS = 24 * 3600
PROBE_STAMP_FILENAME = "last_google_probe.txt"


# -- classification (pure, no I/O) ----------------------------------


def classify_refresh_response(_status_code: int | None, body: dict | None) -> str:
    """Classify a token-endpoint refresh response.

    A successful refresh carries an ``access_token``. Otherwise the ``error`` code
    decides: ``invalid_grant`` is a bad user token (re-auth), while
    ``deleted_client`` / ``invalid_client`` (or an error whose description says the
    client was "not found") is a dead client (swap it). Anything else is unknown
    and deliberately NOT treated as a dead client, so a transient upstream blip
    never triggers a spurious client swap or notification.
    """
    body = body or {}
    if body.get("access_token"):
        return HEALTHY
    err = str(body.get("error") or "").strip().lower()
    desc = str(body.get("error_description") or "").lower()
    if err == "invalid_grant":
        return BAD_TOKEN
    if err in ("deleted_client", "invalid_client"):
        return DEAD_CLIENT
    # Some responses carry a generic error but say "not found" for the client in
    # the description; that is the exact ...t1glqf failure signature.
    if "not found" in desc and "client" in desc:
        return DEAD_CLIENT
    return UNKNOWN


# -- token endpoint call (the one network side effect) --------------


def _post_token(token_url: str, params: dict, timeout: int = 20) -> tuple[int, dict]:
    """POST an OAuth token request; return ``(http_status, json_body)``.

    Refresh failures come back as HTTP 400/401 with a JSON error body, so the
    HTTPError branch parses and returns that body rather than raising.
    """
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        token_url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return getattr(r, "status", 200), json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body: dict = {}
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {}
        return e.code, body


def probe_refresh(
    client_id: str,
    client_secret: str | None,
    refresh_token: str,
    token_url: str = DEFAULT_TOKEN_URL,
    *,
    post=None,
) -> tuple[str, int | None, dict]:
    """Attempt a token refresh and classify it. Returns ``(classification, status, body)``."""
    post = post or _post_token
    params = {
        "client_id": client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    if client_secret:
        params["client_secret"] = client_secret
    status, body = post(token_url, params)
    return classify_refresh_response(status, body), status, body


# -- account-level probe (gated to Gmail) ---------------------------


def _is_google(provider: str, profile: dict) -> bool:
    return provider == "gmail" or profile.get("auth_strategy") == "loopback-oauth"


def probe_account(account: str, *, post=None) -> dict:
    """Probe one account's Google client health via a stored-token refresh.

    Skips (never a false dead-client) when the account is not Google or has no
    stored refresh token yet (brand-new user). Does no self-heal; see
    :func:`run_probe`.
    """
    import imap_client as ic  # lazy: pulls imap_tools/msal from the runtime venv

    provider, profile = ic.account_profile(account)
    if not _is_google(provider, profile):
        return {"account": account, "provider": provider, "status": SKIPPED, "reason": "not a Google account"}
    tok = ic.load_token(account)
    if not tok or not tok.get("refresh_token"):
        return {"account": account, "provider": provider, "status": SKIPPED, "reason": "no stored refresh token"}

    token_url = profile.get("oauth_token_url") or DEFAULT_TOKEN_URL
    client_id = profile["oauth_client_id"]
    client_secret = profile.get("oauth_client_secret")
    classification, status, body = probe_refresh(client_id, client_secret, tok["refresh_token"], token_url, post=post)
    return {
        "account": account,
        "provider": provider,
        "status": classification,
        "http_status": status,
        "error": body.get("error"),
        "error_description": body.get("error_description"),
        "client_id": client_id,
    }


# -- self-heal ------------------------------------------------------


def attempt_self_heal(account: str, dead_result: dict, *, post=None, allow_fetch: bool = True) -> dict:
    """Re-resolve Thunderbird's current client and retry the refresh once.

    Force-refreshes the dynamic client from comm-central, then retries the token
    refresh with the fresh client id/secret. If the fresh id matches the dead one
    there is nothing to swap to. A successful retry means the freshly-fetched
    client is now cached, so every subsequent profile build picks it up
    automatically — the swap is durable, not just for this call.
    """
    import providers
    from thunderbird_client import resolve_google_client

    creds = resolve_google_client(
        providers.THUNDERBIRD_GOOGLE_CLIENT_ID,
        providers.THUNDERBIRD_GOOGLE_CLIENT_SECRET,
        force_refresh=True,
        allow_fetch=allow_fetch,
    )
    new_id = creds["client_id"]
    new_secret = creds["client_secret"]
    if new_id == dead_result.get("client_id"):
        return {
            "status": UNKNOWN,
            "healed": False,
            "reason": "freshly-resolved client id is identical to the dead one",
            "source": creds["source"],
            "client_id": new_id,
        }

    import imap_client as ic

    tok = ic.load_token(account)
    _, profile = ic.account_profile(account)
    token_url = profile.get("oauth_token_url") or DEFAULT_TOKEN_URL
    classification, status, body = probe_refresh(new_id, new_secret, tok["refresh_token"], token_url, post=post)
    healed = classification == HEALTHY
    return {
        "status": classification,
        "healed": healed,
        "source": creds["source"],
        "client_id": new_id,
        "http_status": status,
        "error": body.get("error"),
    }


# -- notification ---------------------------------------------------


def write_dead_client_notification(account: str, result: dict) -> pathlib.Path:
    """Write a clear, human-readable dead-client alert (interrupt=true)."""
    NOTIF_DIR.mkdir(parents=True, exist_ok=True)
    notif = {
        "source": "email-client",
        "type": "google_client_dead",
        # This is not routine mail — the whole Gmail integration is down and
        # needs a human to swap in a new verified client, so it interrupts.
        "interrupt": True,
        "account": account,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "message": (
            "Gmail stopped working: the shared Google sign-in client was removed "
            "upstream and needs replacing. Automatic recovery via Thunderbird's "
            "latest published client did not succeed, so Gmail send/receive is "
            f"down for account '{account}' until a new verified public client is "
            "put in place. This is not a problem with your account or password."
        ),
        "detail": {
            "oauth_error": result.get("error"),
            "oauth_error_description": result.get("error_description"),
            "http_status": result.get("http_status"),
            "dead_client_id": result.get("client_id"),
            "self_heal": result.get("self_heal"),
        },
    }
    fname = f"email-client-google_client_dead-{account}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}.json"
    final = NOTIF_DIR / fname
    tmp = NOTIF_DIR / f"{fname}.tmp"
    tmp.write_text(json.dumps(notif, ensure_ascii=False, indent=2))
    tmp.replace(final)
    return final


# -- top-level orchestration ----------------------------------------


def run_probe(account: str, *, post=None, notify: bool = True, allow_fetch: bool = True) -> dict:
    """Probe one account; on a dead client, self-heal, then notify if unhealed."""
    result = probe_account(account, post=post)
    if result["status"] != DEAD_CLIENT:
        return result

    heal = attempt_self_heal(account, result, post=post, allow_fetch=allow_fetch)
    result["self_heal"] = heal
    if heal.get("healed"):
        result["status"] = HEALED
        return result

    if notify:
        path = write_dead_client_notification(account, result)
        result["notification"] = str(path)
    return result


def _gmail_accounts() -> list[str]:
    import imap_client as ic

    out = []
    for acc in ic.list_accounts():
        provider, profile = ic.account_profile(acc)
        if _is_google(provider, profile):
            out.append(acc)
    return out


def run_probe_all(*, post=None, notify: bool = True, allow_fetch: bool = True) -> list[dict]:
    """Probe every registered Gmail account."""
    return [run_probe(acc, post=post, notify=notify, allow_fetch=allow_fetch) for acc in _gmail_accounts()]


# -- daemon hook (daily, low-frequency) -----------------------------


def _stamp_path(state_dir: pathlib.Path) -> pathlib.Path:
    return state_dir / PROBE_STAMP_FILENAME


def _due(state_dir: pathlib.Path, now: float) -> bool:
    p = _stamp_path(state_dir)
    if not p.exists():
        return True
    try:
        last = float(p.read_text().strip() or 0)
    except Exception:
        return True
    return (now - last) >= PROBE_INTERVAL_SECS


def maybe_run_daily_probe(state_dir: pathlib.Path, log=None, *, now: float | None = None) -> list[dict] | None:
    """Run the probe across Gmail accounts at most once per day.

    Called from the poll daemon's supervisor loop every cycle; returns None when
    it is not yet due, so the common case is a single cheap timestamp read. The
    stamp is written before probing so a probe error cannot spin the loop.
    """
    now = now if now is not None else time.time()
    if not _due(state_dir, now):
        return None
    _stamp_path(state_dir).write_text(str(now))
    if log:
        log("[google-health] running daily OAuth client probe")
    results = run_probe_all()
    if log:
        for r in results:
            if r["status"] in (DEAD_CLIENT, HEALED):
                log(f"[google-health] {r['account']}: {r['status']} (self-heal={r.get('self_heal', {}).get('healed')})")
            else:
                log(f"[google-health] {r['account']}: {r['status']}")
    return results
