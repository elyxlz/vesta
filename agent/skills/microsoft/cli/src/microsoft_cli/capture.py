"""Browser-capture edge module: the single place that drives the ``browser`` skill to lift
Microsoft web-session tokens on a locked tenant, and to refresh them with no user in the loop.

A locked tenant hands out no MSAL refresh token, so the browser session itself is the credential.
Each account owns one Chromium session, ``microsoft-<the address in ASCII>``: the user signs in once
through a handover on that session, and its SSO cookies live on there. Every capture afterwards runs
one ``browser exec`` program on that same session (open the web app, wait for the load, read the
token the SPA minted from the still-valid cookies), so onboarding and silent refresh share one path,
and the silent refresh opens no view for the user.

All ``browser`` subprocess calls live here so the coupling to that skill stays in one module.
"""

from __future__ import annotations

import hashlib
import json
import re
import string
import subprocess
import time
import typing as tp

from . import owa_rest, teams

MAIL_URL = "https://outlook.office.com/mail/"
TEAMS_URL = "https://teams.microsoft.com/v2/"

# Re-capture this many seconds before a token expires, so a fresh one is always in hand.
REFRESH_MARGIN_SECS = 2 * 60 * 60

# The `browser` CLI answers its own RPC inside these; the subprocess budget adds the slack on top.
TOKEN_TIMEOUT_SECS = 60.0
HANDOVER_TIMEOUT_SECS = 150.0
RPC_SLACK_SECS = 30
HANDOVER_MINUTES = 30

# The session-name shape the browser daemon takes, and the length it caps a name at.
SESSION_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SESSION_NAME_MAX = 64
_SESSION_PREFIX = "microsoft-"
_SESSION_ALPHABET = frozenset(string.ascii_lowercase + string.digits)
_SESSION_DIGEST_CHARS = 8

TokenKind = tp.Literal["mail", "teams"]
TOKEN_KINDS: tuple[TokenKind, ...] = ("mail", "teams")
JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


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

_TOKEN_SOURCES: dict[TokenKind, tuple[str, str]] = {"mail": (MAIL_URL, _MAIL_TOKEN_JS), "teams": (TEAMS_URL, _TEAMS_TOKEN_JS)}

# The program `browser exec` runs: drive this session's one tab to the web app and print its token.
# Each poll navigates the tab it finds, so a run of polls holds one tab open, not one per poll.
_TOKEN_PROGRAM = """if not list_tabs():
    new_tab({url!r})
goto_url({url!r})
wait_for_load()
print(js({expression!r}))
"""


def session_name(account_email: str) -> str:
    """The Chromium session that holds this account's sign-in. One account, one session.

    The daemon takes `SESSION_NAME_RE`, so the address maps to ASCII lowercase alphanumerics with
    every other character replaced by `_`. An address that overruns `SESSION_NAME_MAX` keeps the
    head that fits plus a digest of the whole address, so the name stays inside the cap, unique to
    the account, and the same on every call.
    """
    address = account_email.lower()
    mapped = "".join(char if char in _SESSION_ALPHABET else "_" for char in address)
    if len(_SESSION_PREFIX) + len(mapped) <= SESSION_NAME_MAX:
        return f"{_SESSION_PREFIX}{mapped}"
    head = SESSION_NAME_MAX - len(_SESSION_PREFIX) - 1 - _SESSION_DIGEST_CHARS
    digest = hashlib.sha256(address.encode()).hexdigest()[:_SESSION_DIGEST_CHARS]
    return f"{_SESSION_PREFIX}{mapped[:head]}-{digest}"


def _send(args: list[str], *, code: str | None = None, timeout: float) -> dict[str, JsonValue]:
    """Run one `browser` command and return its answer envelope. Any failure is a CaptureError."""
    try:
        result = subprocess.run(["browser", *args], input=code, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise CaptureError("the `browser` skill is not active; cannot capture Microsoft tokens on a locked tenant") from exc
    except subprocess.TimeoutExpired as exc:
        raise CaptureError(f"the browser did not answer within {int(timeout)}s") from exc
    line = result.stdout.strip() or result.stderr.strip()
    try:
        envelope = json.loads(line)
    except json.JSONDecodeError:
        raise CaptureError(f"unexpected browser output: {line[:120]!r}") from None
    if not isinstance(envelope, dict) or "ok" not in envelope:
        raise CaptureError(f"unexpected browser output: {line[:120]!r}")
    if not envelope["ok"]:
        error = envelope["error"]
        message = error["message"]
        raise CaptureError(f"start the browser daemon: {message}" if error["code"] == "daemon_down" else message)
    return envelope


def _exec(code: str, *, session: str, timeout: float) -> str:
    """Run a Python program on `session` and return what it printed."""
    args = ["exec", "--session", session, "--timeout", str(int(timeout))]
    envelope = _send(args, code=code, timeout=timeout + RPC_SLACK_SECS)
    output = envelope["output"]
    if not isinstance(output, dict) or "stdout" not in output or not isinstance(output["stdout"], str):
        raise CaptureError("the browser answered without the program's output")
    return output["stdout"].strip()


def eval_value(raw: str) -> str:
    """Unwrap what the page evaluation prints: a JSON-encoded JS result arrives quoted."""
    return json.loads(raw) if raw.startswith('"') else raw


def _looks_like_jwt(value: str) -> bool:
    return value.count(".") == 2 and value.startswith("eyJ")


def capture_token(_config, account_email: str, kind: TokenKind) -> str | None:
    """Read one token from this account's browser session. None means the session is not signed in.

    The account's session carries the whole sign-in, so the config holds nothing this needs."""
    url, expression = _TOKEN_SOURCES[kind]
    code = _TOKEN_PROGRAM.format(url=url, expression=expression)
    value = eval_value(_exec(code, session=session_name(account_email), timeout=TOKEN_TIMEOUT_SECS))
    return value if _looks_like_jwt(value) else None


def _poll_token(account_email: str, kind: TokenKind, *, tries: int = 12, delay: float = 2.5) -> str | None:
    """Read the token until it appears: the SPA mints it a few seconds into the load."""
    for attempt in range(tries):
        token = capture_token(None, account_email, kind)
        if token is not None:
            return token
        if attempt + 1 < tries:
            time.sleep(delay)
    return None


def begin_interactive(_config, account_email: str) -> str:
    """Open a handover on this account's session and return the URL to hand the user."""
    args = ["handover", "start", "--session", session_name(account_email), "--url", MAIL_URL, "--minutes", str(HANDOVER_MINUTES)]
    envelope = _send(args, timeout=HANDOVER_TIMEOUT_SECS)
    data = envelope["data"]
    if not isinstance(data, dict) or "user_url" not in data or not isinstance(data["user_url"], str):
        raise CaptureError("the browser started no sign-in window")
    return data["user_url"]


def _harvest(account_email: str) -> dict[str, dict[str, float | str]]:
    """Lift the mail and Teams tokens from the account's session. Skips a token that never appears
    (e.g. Teams not provisioned) rather than failing the whole capture."""
    captured: dict[str, dict[str, float | str]] = {}
    for kind in TOKEN_KINDS:
        token = _poll_token(account_email, kind)
        if token:
            captured[kind] = {"token": token, "expires_at": owa_rest.jwt_exp(token)}
    return captured


def finish_interactive(_config, account_email: str) -> dict[str, dict[str, float | str]]:
    """After the user has signed in, close the handover window and lift both tokens from the session."""
    # The stop detaches the user's view; the session keeps running signed in, so the harvest
    # reads it directly.
    stop()
    captured = _harvest(account_email)
    if not captured:
        raise CaptureError("no signed-in browser session; run the sign-in step first")
    return captured


def refresh(_config, account_email: str) -> dict[str, dict[str, float | str]]:
    """Silently re-mint tokens: read them from the account's session with no window and no user.

    Works while the SSO cookies live (weeks with "stay signed in"); raises once they lapse so the
    caller can ask the user to sign in again."""
    captured = _harvest(account_email)
    if not captured:
        raise CaptureError(f"sign-in for {account_email} has expired; run: microsoft auth setup --account {account_email} --browser")
    return captured


def stop() -> None:
    """Close the handover. The account's session keeps its profile, so the sign-in survives, and a
    stop with nothing to stop is not a failure, which makes this idempotent."""
    try:
        _send(["handover", "stop"], timeout=HANDOVER_TIMEOUT_SECS)
    except CaptureError:
        return


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
