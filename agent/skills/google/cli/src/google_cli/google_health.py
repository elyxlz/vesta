#!/usr/bin/env python3
"""Google OAuth client health-probe + automatic self-heal escalation ladder.

The google skill rides Thunderbird's PUBLIC verified Google OAuth client. If that
shared client is deleted or rotated upstream (as the previous ...t1glqf client
was), Gmail silently breaks until someone notices. This module detects that
condition WITHOUT any fresh user interaction and recovers from it automatically
where possible.

How the probe works: it attempts an OAuth token refresh using the account's
already-STORED refresh token and classifies the error:

    deleted_client / invalid_client / "not found"  ->  the CLIENT is dead
                                                        (swap the client id)
    invalid_grant                                   ->  the USER TOKEN is bad
                                                        (re-auth; client is fine)
    success                                         ->  healthy

Only a dead client triggers the self-heal escalation ladder (see
:func:`run_self_heal_cycle`). The ladder is deliberately quiet: it re-fetches the
live Thunderbird client and swaps it in silently first, and only ever reaches the
user as a genuine last resort.

This is Google-specific. It never sends mail and never touches the mailbox;
EMAIL_DRAFT_ONLY is irrelevant here.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

from .thunderbird_client import (
    THUNDERBIRD_GOOGLE_CLIENT_ID,
    THUNDERBIRD_GOOGLE_CLIENT_SECRET,
    resolve_google_client,
)

# Probe outcome classifications.
HEALTHY = "healthy"
DEAD_CLIENT = "dead_client"
BAD_TOKEN = "bad_token"
UNKNOWN = "unknown"
SKIPPED = "skipped"
HEALED = "healed"

DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"

DEFAULT_NOTIF_DIR = pathlib.Path.home() / "agent" / "notifications"

# Run the daemon-driven probe at most this often (once a day, not every poll).
PROBE_INTERVAL_SECS = 24 * 3600
PROBE_STAMP_FILENAME = "last_google_probe.txt"

# Markers tracking the escalation ladder state (live in the skill data dir).
HEAL_REQUEST_MARKER = "google_client_heal_request.marker"
USER_NOTIFIED_MARKER = "google_client_user_notified.marker"


# -- classification (pure, no I/O) ----------------------------------


def classify_refresh_response(status_code: int | None, body: dict | None) -> str:
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


# -- token storage helpers (this skill's single-account model) ------


def _load_token(config) -> dict | None:
    p = config.token_file
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _rewrite_token_client(config, client_id: str, client_secret: str) -> None:
    """Persist a swapped client id/secret into the stored token.

    After a successful heal every subsequent refresh (which reads client_id/secret
    straight out of token.json) uses the fresh client, so the swap is durable.
    """
    tok = _load_token(config)
    if not tok:
        return
    tok["client_id"] = client_id
    tok["client_secret"] = client_secret
    p = config.token_file
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(tok, indent=2))
    os.replace(tmp, p)


# -- account-level probe --------------------------------------------


def probe_config(config, *, post=None) -> dict:
    """Probe the account's Google client health via a stored-token refresh.

    Skips (never a false dead-client) when there is no stored refresh token yet
    (brand-new user). Tests the client id/secret stored in token.json — the exact
    values a live refresh uses. Does no self-heal; see :func:`run_self_heal_cycle`.
    """
    tok = _load_token(config)
    if not tok or not tok.get("refresh_token"):
        return {"status": SKIPPED, "reason": "no stored refresh token"}

    client_id = tok.get("client_id")
    client_secret = tok.get("client_secret")
    token_url = tok.get("token_uri") or DEFAULT_TOKEN_URL
    if not client_id:
        return {"status": SKIPPED, "reason": "stored token has no client_id"}

    classification, status, body = probe_refresh(client_id, client_secret, tok["refresh_token"], token_url, post=post)
    return {
        "status": classification,
        "http_status": status,
        "error": body.get("error"),
        "error_description": body.get("error_description"),
        "client_id": client_id,
    }


# -- self-heal ------------------------------------------------------


def attempt_self_heal(config, dead_result: dict, *, post=None, allow_fetch: bool = True) -> dict:
    """Re-resolve Thunderbird's current client and retry the refresh once.

    Force-refreshes the dynamic client from comm-central, then retries the token
    refresh with the fresh client id/secret. If the fresh id matches the dead one
    there is nothing to swap to. On a successful retry the fresh client is written
    both into the resolver cache and into token.json, making the swap durable.
    """
    creds = resolve_google_client(
        THUNDERBIRD_GOOGLE_CLIENT_ID,
        THUNDERBIRD_GOOGLE_CLIENT_SECRET,
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

    tok = _load_token(config)
    token_url = (tok.get("token_uri") if tok else None) or DEFAULT_TOKEN_URL
    classification, status, body = probe_refresh(new_id, new_secret, tok["refresh_token"], token_url, post=post)
    healed = classification == HEALTHY
    if healed:
        _rewrite_token_client(config, new_id, new_secret)
    return {
        "status": classification,
        "healed": healed,
        "source": creds["source"],
        "client_id": new_id,
        "http_status": status,
        "error": body.get("error"),
    }


# -- notifications --------------------------------------------------


def _write_notification(notif_dir: pathlib.Path, notif: dict, kind: str) -> pathlib.Path:
    notif_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{int(time.time() * 1e6)}-google-{kind}.json"
    final = notif_dir / fname
    tmp = notif_dir / f"{fname}.tmp"
    tmp.write_text(json.dumps(notif, ensure_ascii=False, indent=2))
    os.replace(tmp, final)
    return final


def write_agent_heal_request(notif_dir: pathlib.Path, result: dict) -> pathlib.Path:
    """LEVEL 2: an AGENT-actionable heal request (not a user-facing alert).

    Phrased for the agent to act on: find/patch a fresh verified public client,
    test it, and upstream the fix. interrupt=True so the agent is woken.
    """
    notif = {
        "source": "google",
        "type": "google_client_heal_request",
        "interrupt": True,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "message": (
            "ACTION NEEDED (agent): the reused Thunderbird Google OAuth client "
            f"'{result.get('client_id')}' is dead (token endpoint returned "
            f"'{result.get('error')}'). Auto re-fetching the live Thunderbird "
            "client from comm-central did NOT yield a working client. Find or patch "
            "a fresh verified public desktop client, test it against the token "
            "endpoint, swap it into thunderbird_client.py / the resolver cache, and "
            "upstream the fix. Do NOT surface this to the user yet — it is an "
            "engineering task for you."
        ),
        "detail": {
            "oauth_error": result.get("error"),
            "oauth_error_description": result.get("error_description"),
            "http_status": result.get("http_status"),
            "dead_client_id": result.get("client_id"),
            "self_heal": result.get("self_heal"),
        },
    }
    return _write_notification(notif_dir, notif, "google_client_heal_request")


def write_user_dead_client_notification(notif_dir: pathlib.Path, result: dict) -> pathlib.Path:
    """LEVEL 3: a clear, plain-English USER alert. The only path that reaches the user."""
    notif = {
        "source": "google",
        "type": "google_client_dead",
        "interrupt": True,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "message": (
            "Gmail and Google Calendar stopped working: the shared Google sign-in "
            "client was removed upstream and automatic recovery did not succeed, so "
            "Google access is down until a new verified sign-in client is put in "
            "place. This is not a problem with your account or password — nothing "
            "you did, and re-entering your password will not fix it."
        ),
        "detail": {
            "oauth_error": result.get("error"),
            "dead_client_id": result.get("client_id"),
        },
    }
    return _write_notification(notif_dir, notif, "google_client_dead")


# -- escalation ladder ----------------------------------------------


def _heal_request_marker(config) -> pathlib.Path:
    return config.data_dir / HEAL_REQUEST_MARKER


def _user_notified_marker(config) -> pathlib.Path:
    return config.data_dir / USER_NOTIFIED_MARKER


def _clear_markers(config) -> None:
    _heal_request_marker(config).unlink(missing_ok=True)
    _user_notified_marker(config).unlink(missing_ok=True)


def run_self_heal_cycle(
    config,
    notif_dir: pathlib.Path,
    *,
    post=None,
    allow_fetch: bool = True,
    log=None,
    now: float | None = None,
) -> dict:
    """Probe the client and run the automatic self-heal escalation ladder.

    On a detected DEAD CLIENT:
      LEVEL 1 (silent): re-fetch the live Thunderbird client, swap it in, re-test.
        Healthy again -> done SILENTLY (cache + token updated, info log, NO notif).
      LEVEL 2 (wake agent): fresh client also dead -> write an agent-actionable
        heal-request notification (interrupt) and a marker, so it is not repeated.
      LEVEL 3 (user, last resort): a heal-request marker already exists from a
        previous cycle and the client is STILL dead -> write a plain-English
        user-facing notification (once).

    A non-dead outcome clears any escalation markers so a later incident starts
    the ladder fresh.
    """
    now = now if now is not None else time.time()
    result = probe_config(config, post=post)
    status = result["status"]

    if status != DEAD_CLIENT:
        # Healthy again (or bad-token / skipped) — recovery resets the ladder.
        if status == HEALTHY:
            _clear_markers(config)
        return result

    # LEVEL 1: silent auto re-fetch + swap.
    heal = attempt_self_heal(config, result, post=post, allow_fetch=allow_fetch)
    result["self_heal"] = heal
    if heal.get("healed"):
        result["status"] = HEALED
        result["escalation"] = "silent_swap"
        _clear_markers(config)
        if log:
            log(
                "[google-health] dead client auto-healed by swapping to the fresh "
                f"Thunderbird client {heal.get('client_id')} (silent, no notification)"
            )
        return result

    marker = _heal_request_marker(config)
    if not marker.exists():
        # LEVEL 2: wake the agent, record a marker so we don't repeat it.
        path = write_agent_heal_request(notif_dir, result)
        marker.write_text(str(now))
        result["escalation"] = "agent_request"
        result["notification"] = str(path)
        if log:
            log("[google-health] dead client not auto-healed; wrote agent heal-request (interrupt)")
        return result

    # LEVEL 3: heal-request marker already exists AND still dead -> tell the user.
    user_marker = _user_notified_marker(config)
    if not user_marker.exists():
        path = write_user_dead_client_notification(notif_dir, result)
        user_marker.write_text(str(now))
        result["escalation"] = "user_notify"
        result["notification"] = str(path)
        if log:
            log("[google-health] dead client still unresolved after agent request; escalated to USER notification")
    else:
        # Already told the user; stay quiet to avoid daily spam (judgment call).
        result["escalation"] = "already_user_notified"
        if log:
            log("[google-health] dead client still unresolved; user already notified, staying quiet")
    return result


def run_probe_once(config, *, post=None, allow_fetch: bool = True) -> dict:
    """Probe + attempt self-heal once, WITHOUT writing any notifications.

    Backs the `auth probe` CLI: gives a human/agent an immediate read on client
    health and a silent recovery attempt, but never files an agent/user alert
    (that is the daemon's job via :func:`run_self_heal_cycle`).
    """
    result = probe_config(config, post=post)
    if result["status"] == DEAD_CLIENT:
        heal = attempt_self_heal(config, result, post=post, allow_fetch=allow_fetch)
        result["self_heal"] = heal
        if heal.get("healed"):
            result["status"] = HEALED
    return result


# -- daemon hook (daily, low-frequency) -----------------------------


def _stamp_path(config) -> pathlib.Path:
    return config.data_dir / PROBE_STAMP_FILENAME


def _due(stamp: pathlib.Path, now: float) -> bool:
    if not stamp.exists():
        return True
    try:
        last = float(stamp.read_text().strip() or 0)
    except Exception:
        return True
    return (now - last) >= PROBE_INTERVAL_SECS


def maybe_run_daily_probe(config, notif_dir: pathlib.Path, log=None, *, now: float | None = None) -> dict | None:
    """Run the probe + self-heal ladder at most once per day.

    Called from the monitor loop every cycle; returns None when not yet due, so
    the common case is one cheap timestamp read. The stamp is written before
    probing so a probe error cannot spin the loop.
    """
    now = now if now is not None else time.time()
    stamp = _stamp_path(config)
    if not _due(stamp, now):
        return None
    stamp.write_text(str(now))
    if log:
        log("[google-health] running daily OAuth client probe")
    result = run_self_heal_cycle(config, notif_dir, log=log, now=now)
    if log:
        log(f"[google-health] probe result: status={result.get('status')} escalation={result.get('escalation')}")
    return result
