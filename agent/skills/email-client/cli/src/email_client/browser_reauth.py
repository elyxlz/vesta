"""Silent Microsoft re-auth through a signed-in browser profile.

Some tenants cap the MFA age of refresh tokens (AADSTS50078), so a plain refresh token
dies after a day or two. Desktop mail clients recover by reopening the sign-in page,
where the browser's persistent Microsoft session usually completes without a prompt.
This does the same headlessly: run the authorization-code flow (PKCE, prompt=none)
inside a `browser` skill session already signed in to the tenant, read the redirect,
and exchange the code. Opt-in per account via `"browser_session": "<name>"` in the
account's config.json. Returns None when the browser session itself needs interaction.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile
import time
import urllib.parse
import uuid

REDIRECT_URI = "https://localhost"
COOLDOWN_SECS = 6 * 3600
NOTIF_DIR = pathlib.Path.home() / "agent" / "notifications"
MFA_EXPIRED_CODES = {50078, 50076, 50079, 50072, 70043, 700082}

_BROWSER_PROGRAM = """
import time
new_tab(url=open(AUTH_URL_FILE).read())
found = ""
for _ in range(25):
    time.sleep(1)
    h = cdp("Page.getNavigationHistory")
    loc = [e.get("url", "") for e in h.get("entries", []) if e.get("url", "").startswith(REDIRECT)]
    if loc:
        found = loc[-1]
        break
with open(RESULT_FILE, "w") as f:
    f.write(found)
close_tab()
print("done" if found else "no-redirect")
"""


def needs_mfa_refresh(res: dict) -> bool:
    codes = set(res.get("error_codes") or [])
    return bool(codes & MFA_EXPIRED_CODES) or res.get("error") == "interaction_required"


def silent_reauth(profile: dict, user: str, session: str, timeout: int = 60) -> dict | None:
    """Mint a fresh token via the browser session, or None if it needs a human."""
    import msal

    app = msal.PublicClientApplication(profile["oauth_client_id"], authority=profile["oauth_authority"])
    flow = app.initiate_auth_code_flow(profile["oauth_scopes"], redirect_uri=REDIRECT_URI, login_hint=user, prompt="none")
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = pathlib.Path(tmp_name)
        tmp.chmod(0o700)
        url_file = tmp / "auth_url"
        result_file = tmp / "redirect"
        url_file.write_text(flow["auth_uri"])
        program = f"AUTH_URL_FILE = {str(url_file)!r}\nRESULT_FILE = {str(result_file)!r}\nREDIRECT = {REDIRECT_URI!r}\n" + _BROWSER_PROGRAM
        proc = subprocess.run(
            ["browser", "exec", "--session", session, "--timeout", str(timeout)],
            input=program,
            capture_output=True,
            text=True,
            timeout=timeout + 30,
            check=False,
        )
        if proc.returncode != 0 or not result_file.exists():
            return None
        redirect = result_file.read_text().strip()
    if not redirect:
        return None
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(redirect).query))
    if "code" not in params:
        return None
    res = app.acquire_token_by_auth_code_flow(flow, params)
    return res if "access_token" in res else None


def _log_path(acc_dir: pathlib.Path) -> pathlib.Path:
    return acc_dir / "browser_reauth.jsonl"


def _attempts(acc_dir: pathlib.Path) -> list[dict]:
    try:
        lines = _log_path(acc_dir).read_text().splitlines()
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


def may_attempt(acc_dir: pathlib.Path) -> bool:
    """At most one browser sign-in per COOLDOWN_SECS, so a tenant never sees a burst."""
    past = _attempts(acc_dir)
    return not past or time.time() - past[-1]["ts"] >= COOLDOWN_SECS


def record(acc_dir: pathlib.Path, account: str, failed: dict, *, ok: bool) -> None:
    """Append to the per-account log and raise one interrupting notification per attempt."""
    now = time.time()
    prev_ok = [a for a in _attempts(acc_dir) if a.get("ok")]
    entry = {
        "ts": now,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now)),
        "ok": ok,
        "trigger": failed.get("error_codes") or failed.get("error"),
        "hours_since_last_ok": round((now - prev_ok[-1]["ts"]) / 3600, 1) if prev_ok else None,
    }
    with _log_path(acc_dir).open("a") as f:
        f.write(json.dumps(entry) + "\n")
    NOTIF_DIR.mkdir(parents=True, exist_ok=True)
    notif = {
        "source": "email-client",
        "type": "browser_reauth",
        "interrupt": True,
        "account": account,
        **{k: entry[k] for k in ("ok", "trigger", "hours_since_last_ok")},
        "attempts_total": len(_attempts(acc_dir)),
        "timestamp": entry["at"],
    }
    fname = f"email-client-browser_reauth-{int(now * 1000)}-{uuid.uuid4().hex[:6]}.json"
    tmp = NOTIF_DIR / f"{fname}.tmp"
    tmp.write_text(json.dumps(notif, indent=2))
    tmp.replace(NOTIF_DIR / fname)
