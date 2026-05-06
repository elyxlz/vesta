"""Programmatic disposable email via mail.tm.

Used to autonomously bootstrap an AgentMail account without asking the user
for an email address. The flow:

    dispo = create_account()
    # ... POST AgentMail /agent/sign-up using dispo["email"] ...
    msg = wait_for_message(dispo["token"], sender_contains="agentmail")
    otp = extract_otp(msg["text"] or msg["html"])
    # ... POST AgentMail /agent/verify with that OTP ...

Caveats:
- AgentMail may block known disposable-email domains via anti-fraud.
- mail.tm itself can rate-limit or be down.

Both failure modes raise RuntimeError; setup surfaces them and instructs the
user to re-run with `--prompt` for the manual flow.
"""

from __future__ import annotations

import re
import secrets
import string
import time

import httpx


BASE = "https://api.mail.tm"
DEFAULT_OTP_TIMEOUT_SECONDS = 180


def _random_local(length: int = 16) -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def _random_password() -> str:
    return secrets.token_urlsafe(24)


def _list_field(body: dict, key: str) -> list:
    if key in body and isinstance(body[key], list):
        return body[key]
    if "hydra:member" in body and isinstance(body["hydra:member"], list):
        return body["hydra:member"]
    return []


def _pick_domain() -> str:
    with httpx.Client(base_url=BASE, timeout=15.0) as c:
        r = c.get("/domains")
        r.raise_for_status()
        domains = _list_field(r.json(), "data")
        if not domains:
            raise RuntimeError("mail.tm returned no domains")
        for d in domains:
            if "domain" in d and "isActive" in d and d["isActive"]:
                return d["domain"]
        return domains[0]["domain"]


def create_account() -> dict:
    """Create a disposable mail.tm account. Returns {email, password, token}."""
    domain = _pick_domain()
    email = f"{_random_local()}@{domain}"
    password = _random_password()
    with httpx.Client(base_url=BASE, timeout=15.0) as c:
        r = c.post("/accounts", json={"address": email, "password": password})
        if r.status_code >= 400:
            raise RuntimeError(f"mail.tm /accounts returned {r.status_code}: {r.text[:200]}")
        tr = c.post("/token", json={"address": email, "password": password})
        if tr.status_code >= 400:
            raise RuntimeError(f"mail.tm /token returned {tr.status_code}: {tr.text[:200]}")
        body = tr.json()
        if "token" not in body:
            raise RuntimeError(f"mail.tm /token response missing token: {body}")
        return {"email": email, "password": password, "token": body["token"]}


def wait_for_message(
    token: str,
    *,
    sender_contains: str,
    timeout: int = DEFAULT_OTP_TIMEOUT_SECONDS,
    poll_interval: int = 3,
) -> dict:
    """Poll the disposable inbox until a message from `sender_contains` arrives.

    Returns the full message dict (with `text` and `html` fields). Raises on
    timeout.
    """
    deadline = time.time() + timeout
    headers = {"Authorization": f"Bearer {token}"}
    needle = sender_contains.lower()
    with httpx.Client(base_url=BASE, headers=headers, timeout=15.0) as c:
        while time.time() < deadline:
            r = c.get("/messages")
            if r.status_code == 200:
                for msg in _list_field(r.json(), "data"):
                    from_obj = msg["from"] if "from" in msg and isinstance(msg["from"], dict) else {}
                    from_addr = from_obj["address"].lower() if "address" in from_obj else ""
                    if needle in from_addr and "id" in msg:
                        full = c.get(f"/messages/{msg['id']}")
                        if full.status_code == 200:
                            return full.json()
            time.sleep(poll_interval)
    raise RuntimeError(f"timed out after {timeout}s waiting for message from '{sender_contains}'")


def extract_otp(message: dict, *, length: int = 6) -> str:
    """Extract a numeric OTP from a parsed mail.tm message.

    Looks at `text` first, then `html`. Default length is 6 digits; many OTPs
    are 6, but we try 4–8 if 6 doesn't match.
    """
    candidates: list[str] = []
    if "text" in message and isinstance(message["text"], str):
        candidates.append(message["text"])
    if "html" in message and isinstance(message["html"], list):
        candidates.extend(p for p in message["html"] if isinstance(p, str))
    if "html" in message and isinstance(message["html"], str):
        candidates.append(message["html"])
    body = "\n".join(candidates)
    if not body:
        raise RuntimeError(f"message has no text/html body: {message}")

    primary = re.search(rf"\b(\d{{{length}}})\b", body)
    if primary:
        return primary.group(1)
    fallback = re.search(r"\b(\d{4,8})\b", body)
    if fallback:
        return fallback.group(1)
    raise RuntimeError("no numeric OTP found in message body")
