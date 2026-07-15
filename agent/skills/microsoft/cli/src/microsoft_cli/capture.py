"""Browser-capture edge module: the single place that drives the ``browser`` skill to lift
Microsoft web-session tokens on a locked tenant, and to refresh them with no user in the loop.

The locked-tenant fallback has no MSAL refresh token, so the trick is the browser *profile*: the
user signs in once through a headed handover, and the SSO cookies persist in a per-account profile
under ``~/.microsoft/browser-profiles/<email>``. Afterwards the daemon reloads that profile headed on
a throwaway Xvfb (the handover engine, minus the human) and the web apps silently re-mint fresh
access tokens from the still-valid cookies. Headless Firefox cannot load the Outlook/Teams SPAs at
all, so headed-on-Xvfb is the only capture path that works; both onboarding and refresh go through it.

All ``browser`` subprocess calls live here so the coupling to that skill stays in one module.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import pathlib as pl

from . import owa_rest, teams

MAIL_URL = "https://outlook.office.com/mail/"
TEAMS_URL = "https://teams.microsoft.com/v2/"
_HANDOVER_SESSION = "handover"

# Re-capture this many seconds before a token expires, so a fresh one is always in hand.
REFRESH_MARGIN_SECS = 2 * 60 * 60


class CaptureError(RuntimeError):
    """A browser-capture step failed (browser skill missing, sign-in lost, token never appeared)."""


# JS run in the signed-in web session. Each returns a bearer JWT or the string ``NONE``.
# Mail: the outlook.office.com token (the only mail token a locked tenant exposes; Graph has none).
_MAIL_TOKEN_JS = """
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

# Teams: among ALL graph.microsoft.com tokens pick the one with the most Teams scopes, so a partial
# token (e.g. the one Outlook mints, which lacks Chat/Presence) never wins over the Teams web app's.
_TEAMS_TOKEN_JS = """
(() => {
  const want = ['Chat.', 'ChannelMessage.', 'Channel.', 'Team.', 'Presence.'];
  let best = null, bestScore = -1;
  for (const store of [localStorage, sessionStorage]) {
    for (let i = 0; i < store.length; i++) {
      const k = store.key(i);
      if (!/accesstoken/i.test(k)) continue;
      try {
        const v = JSON.parse(store.getItem(k));
        const t = v.target || '';
        if (!t.includes('graph.microsoft.com')) continue;
        const score = want.reduce((n, s) => n + (t.includes(s) ? 1 : 0), 0);
        if (score > bestScore) { bestScore = score; best = v.secret; }
      } catch (e) {}
    }
  }
  return best || 'NONE';
})()
""".strip()


def profile_dir(config, account_email: str) -> pl.Path:
    return pl.Path(config.data_dir) / "browser-profiles" / account_email


def _run(args: list[str], *, session: str | None = None, timeout: float = 120.0) -> str:
    """Invoke the ``browser`` CLI. DISPLAY/WAYLAND are stripped so handover provisions its own Xvfb
    rather than grabbing an ambient desktop seat."""
    env = dict(os.environ)
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    if session:
        env["BROWSER_SESSION"] = session
    try:
        result = subprocess.run(["browser", *args], capture_output=True, text=True, env=env, timeout=timeout)
    except FileNotFoundError as exc:
        raise CaptureError("the `browser` skill is not installed; cannot capture Microsoft tokens on a locked tenant") from exc
    except subprocess.TimeoutExpired:
        return ""
    return result.stdout.strip()


def _eval(js: str) -> str:
    return _run(["evaluate", js], session=_HANDOVER_SESSION, timeout=40)


def _looks_like_jwt(value: str) -> bool:
    return value.count(".") == 2 and value.startswith("eyJ")


def _poll_token(js: str, *, tries: int = 12, delay: float = 2.5) -> str | None:
    """Evaluate ``js`` until it yields a JWT (the SPA mints the token a few seconds into load)."""
    for _ in range(tries):
        raw = _eval(js)
        token = json.loads(raw) if raw.startswith('"') else raw
        if isinstance(token, str) and _looks_like_jwt(token):
            return token
        time.sleep(delay)
    return None


def begin_interactive(config, account_email: str) -> str:
    """Open a headed handover at the Microsoft sign-in and return the URL to hand the user."""
    profile = profile_dir(config, account_email)
    profile.mkdir(parents=True, exist_ok=True)
    _run(["stop-all"], timeout=30)
    out = _run(["handover", "start", "--url", MAIL_URL, "--user-data-dir", str(profile)], timeout=120)
    data = json.loads(out) if out.startswith("{") else {}
    if "user_url" not in data:
        raise CaptureError(f"could not start the sign-in browser: {out or 'no output'}")
    return data["user_url"]


def _harvest(config, account_email: str) -> dict[str, dict[str, float | str]]:
    """From the running (signed-in) handover session, lift the mail and Teams tokens. Skips a token
    that never appears (e.g. Teams not provisioned) rather than failing the whole capture."""
    captured: dict[str, dict[str, float | str]] = {}

    _run(["open", MAIL_URL], session=_HANDOVER_SESSION, timeout=90)
    mail = _poll_token(_MAIL_TOKEN_JS)
    if mail:
        captured["mail"] = {"token": mail, "expires_at": owa_rest.jwt_exp(mail)}

    _run(["open", TEAMS_URL], session=_HANDOVER_SESSION, timeout=90)
    teams = _poll_token(_TEAMS_TOKEN_JS)
    if teams:
        captured["teams"] = {"token": teams, "expires_at": owa_rest.jwt_exp(teams)}

    return captured


def finish_interactive(config, account_email: str) -> dict[str, dict[str, float | str]]:
    """After the user has signed in, lift both tokens, then tear the browser down."""
    if _run(["snapshot"], session=_HANDOVER_SESSION, timeout=30) == "":
        raise CaptureError("no signed-in browser session; run the sign-in step first")
    try:
        return _harvest(config, account_email)
    finally:
        stop()


def refresh(config, account_email: str) -> dict[str, dict[str, float | str]]:
    """Silently re-mint tokens: reload the saved profile headed-on-Xvfb (no user) and lift them.

    Works while the SSO cookies live (weeks with "stay signed in"); raises once they lapse so the
    caller can ask the user to sign in again."""
    profile = profile_dir(config, account_email)
    if not profile.is_dir():
        raise CaptureError(f"no saved browser profile for {account_email}; run: microsoft auth setup --account {account_email} --browser")
    _run(["stop-all"], timeout=30)
    out = _run(["handover", "start", "--url", MAIL_URL, "--user-data-dir", str(profile)], timeout=120)
    if not out.startswith("{"):
        raise CaptureError(f"could not start the refresh browser: {out or 'no output'}")
    try:
        captured = _harvest(config, account_email)
    finally:
        stop()
    if not captured:
        raise CaptureError(f"sign-in for {account_email} has expired; run: microsoft auth setup --account {account_email} --browser")
    return captured


def stop() -> None:
    _run(["handover", "stop"], timeout=30)
    _run(["stop-all"], timeout=30)


def save_captured(config, account_email: str, captured: dict[str, dict[str, float | str]]) -> list[str]:
    """Persist captured tokens (mail over OWA REST, Teams over Graph). Returns what was saved."""
    saved = []
    if "mail" in captured:
        owa_rest.save_token(account_email, config, token=captured["mail"]["token"], expires_at=captured["mail"]["expires_at"], source="browser")
        saved.append("mail/calendar")
    if "teams" in captured:
        teams.save_token(account_email, config, token=captured["teams"]["token"], expires_at=captured["teams"]["expires_at"], source="browser")
        saved.append("Teams")
    return saved


def due_accounts(config, now: float) -> list[str]:
    """Browser-captured accounts whose mail or Teams token expires within the refresh margin."""
    accounts = set(owa_rest.list_accounts(config)) | set(teams.list_accounts(config))
    due = []
    for account in accounts:
        expiries = [e for e in (owa_rest.browser_token_expiry(account, config), teams.browser_token_expiry(account, config)) if e is not None]
        if expiries and min(expiries) - now <= REFRESH_MARGIN_SECS:
            due.append(account)
    return due


def refresh_and_save(config, account_email: str) -> list[str]:
    """Silently re-mint and persist an account's tokens. Raises CaptureError if the sign-in lapsed."""
    return save_captured(config, account_email, refresh(config, account_email))
