"""OWA REST transport: outlook.office.com/api/v2.0 with a browser-captured token.

The OWA web client authenticates with MSAL.js; its access token for the
outlook.office.com resource is stored in the page's localStorage/sessionStorage.
Capturing that token (see ``auth_commands.owa_login``) gives us a JWT with REST
scopes that works against this API.  It does NOT carry the ``EWS.AccessAsUser.All``
scope, so it is useless against the EWS endpoint -- use this path only when EWS is
unavailable (e.g. a university tenant that blocks the device-flow grant).

The OWA REST API (`/api/v2.0`) uses the same paths and semantics as Microsoft
Graph v1.0 but PascalCases every field name.  A recursive key-case converter makes
responses look like Graph so the rest of the CLI (``email.py``, ``calendar.py``) works
unchanged.  Request bodies and ``$select`` field lists are converted the other way.

Token lifetime is ~24 h.  ``has_valid_token`` lets callers probe availability
without a network round-trip; ``load_token`` raises ``OwaRestNoToken`` (a
RuntimeError subclass) when the token is absent or expired.
"""

from __future__ import annotations

import base64
import json
import pathlib as pl
import time
from typing import Any

import httpx

OWA_REST_BASE = "https://outlook.office.com/api/v2.0"

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class OwaRestError(RuntimeError):
    """An OWA REST API call returned an unexpected error."""


class OwaRestNoToken(OwaRestError):
    """No valid browser-captured token is on disk; the user must run owa-login."""


# ---------------------------------------------------------------------------
# Key-case adapter (proven live against a locked UCL tenant)
# ---------------------------------------------------------------------------


def _to_pascal(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _to_camel(s: str) -> str:
    return s[:1].lower() + s[1:] if s else s


def conv_keys(obj: Any, fn) -> Any:
    """Recursively rename dict keys with ``fn``, leaving ``@``-prefixed keys alone."""
    if isinstance(obj, dict):
        return {(k if k.startswith("@") else fn(k)): conv_keys(v, fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [conv_keys(x, fn) for x in obj]
    return obj


def _select_to_pascal(select: str) -> str:
    """Convert a comma-separated camelCase ``$select`` list to PascalCase."""
    return ",".join(_to_pascal(f.strip()) for f in select.split(","))


# ---------------------------------------------------------------------------
# Token file management
# ---------------------------------------------------------------------------

_TOKEN_SUBDIR = "owa_rest_tokens"
_TOKEN_EXPIRY_MARGIN = 60  # seconds: treat a token as expired this many seconds early


def _token_path(account_email: str, config) -> pl.Path:
    return pl.Path(config.data_dir) / _TOKEN_SUBDIR / f"{account_email}.json"


def has_valid_token(account_email: str, config) -> bool:
    """Return True without network I/O if a non-expired token is on disk."""
    try:
        d = json.loads(_token_path(account_email, config).read_text())
        return float(d["expires_at"]) > time.time() + _TOKEN_EXPIRY_MARGIN
    except (FileNotFoundError, KeyError, ValueError):
        return False


def load_token(account_email: str, config) -> str:
    """Return the stored token or raise OwaRestNoToken."""
    p = _token_path(account_email, config)
    try:
        d = json.loads(p.read_text())
    except FileNotFoundError:
        raise OwaRestNoToken(f"No OWA REST token for {account_email}. Run: microsoft auth owa-login --account {account_email}")
    if float(d["expires_at"]) <= time.time() + _TOKEN_EXPIRY_MARGIN:
        raise OwaRestNoToken(f"OWA REST token expired for {account_email}. Run: microsoft auth owa-login --account {account_email}")
    return d["token"]


def save_token(account_email: str, config, *, token: str, expires_at: float) -> None:
    """Persist a browser-captured token.  Never log the token value."""
    p = _token_path(account_email, config)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"token": token, "expires_at": expires_at}))


def jwt_exp(token: str) -> float:
    """Decode the ``exp`` claim from a JWT without signature verification."""
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError("token is not a JWT")
    payload = parts[1]
    payload += "=" * (4 - len(payload) % 4)
    return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _prep_params(params: dict | None) -> dict | None:
    if not params or "$select" not in params:
        return params
    out = dict(params)
    out["$select"] = _select_to_pascal(out["$select"])
    return out


def _get(client: httpx.Client, token: str, path: str, params: dict | None = None) -> Any:
    resp = client.get(f"{OWA_REST_BASE}{path}", headers=_auth_headers(token), params=_prep_params(params))
    resp.raise_for_status()
    return conv_keys(resp.json(), _to_camel)


def _get_raw_bytes(client: httpx.Client, token: str, path: str) -> bytes:
    resp = client.get(f"{OWA_REST_BASE}{path}", headers={"Authorization": f"Bearer {token}", "Accept": "*/*"})
    resp.raise_for_status()
    return resp.content


def _post(client: httpx.Client, token: str, path: str, body: Any = None) -> Any:
    pascal_body = conv_keys(body, _to_pascal) if body is not None else None
    resp = client.post(f"{OWA_REST_BASE}{path}", headers={**_auth_headers(token), **_JSON_HEADERS}, json=pascal_body)
    resp.raise_for_status()
    if not resp.content:
        return {}
    return conv_keys(resp.json(), _to_camel)


def _patch(client: httpx.Client, token: str, path: str, body: Any) -> Any:
    pascal_body = conv_keys(body, _to_pascal)
    resp = client.patch(f"{OWA_REST_BASE}{path}", headers={**_auth_headers(token), **_JSON_HEADERS}, json=pascal_body)
    resp.raise_for_status()
    if not resp.content:
        return {}
    return conv_keys(resp.json(), _to_camel)


def _delete(client: httpx.Client, token: str, path: str) -> None:
    resp = client.delete(f"{OWA_REST_BASE}{path}", headers=_auth_headers(token))
    resp.raise_for_status()


def _paginate(client: httpx.Client, token: str, path: str, params: dict, limit: int) -> list[Any]:
    """Collect items following @odata.nextLink until ``limit`` reached."""
    results: list[Any] = []
    resp = _get(client, token, path, params)
    while True:
        results.extend(resp.get("value", []))
        if len(results) >= limit:
            break
        next_link = resp.get("@odata.nextLink")
        if not next_link:
            break
        # nextLink is the full URL; strip the base so _get can prepend it again.
        rel = next_link.replace(OWA_REST_BASE, "")
        resp = _get(client, token, rel)
    return results[:limit]


# ---------------------------------------------------------------------------
# Folder name normalisation
# ---------------------------------------------------------------------------

_FOLDER_MAP = {
    "inbox": "inbox",
    "sent": "sentitems",
    "sentitems": "sentitems",
    "drafts": "drafts",
    "deleted": "deleteditems",
    "deleteditems": "deleteditems",
    "junk": "junkemail",
    "junkemail": "junkemail",
    "archive": "archive",
}

_MSG_SELECT = (
    "id,subject,receivedDateTime,sentDateTime,isRead,hasAttachments,from,toRecipients,ccRecipients,categories,conversationId,bodyPreview"
)


def _folder_id(name: str | None) -> str:
    key = (name or "inbox").casefold()
    return _FOLDER_MAP.get(key, key)


# ---------------------------------------------------------------------------
# Mail: read
# ---------------------------------------------------------------------------


def list_messages(client: httpx.Client, account_email: str, config, *, folder: str = "inbox", limit: int = 10) -> list[dict]:
    token = load_token(account_email, config)
    fid = _folder_id(folder)
    params = {
        "$select": _MSG_SELECT,
        "$orderby": "ReceivedDateTime desc",
        "$top": str(min(limit, 100)),
    }
    return _paginate(client, token, f"/me/mailfolders/{fid}/messages", params, limit)


def search_messages(client: httpx.Client, account_email: str, config, *, query: str, folder: str | None = None, limit: int = 10) -> list[dict]:
    token = load_token(account_email, config)
    fid = _folder_id(folder or "inbox")
    params: dict = {
        "$select": _MSG_SELECT,
        "$search": f'"{query}"',
        "$top": str(min(limit, 100)),
    }
    return _paginate(client, token, f"/me/mailfolders/{fid}/messages", params, limit)


def get_message(client: httpx.Client, account_email: str, config, *, item_id: str) -> dict:
    token = load_token(account_email, config)
    full_select = _MSG_SELECT + ",body,attachments"
    return _get(client, token, f"/me/messages/{item_id}", {"$select": full_select, "$expand": "Attachments"})


# ---------------------------------------------------------------------------
# Mail: write
# ---------------------------------------------------------------------------


def _recipient(address: str) -> dict:
    return {"emailAddress": {"address": address}}


def _message_body(subject: str, body: str, to: list[str] | None, cc: list[str] | None, bcc: list[str] | None, html: bool) -> dict:
    content_type = "HTML" if html else "Text"
    msg: dict[str, Any] = {
        "subject": subject,
        "body": {"contentType": content_type, "content": body},
    }
    if to:
        msg["toRecipients"] = [_recipient(a) for a in to]
    if cc:
        msg["ccRecipients"] = [_recipient(a) for a in cc]
    if bcc:
        msg["bccRecipients"] = [_recipient(a) for a in bcc]
    return msg


def send_message(
    client: httpx.Client,
    account_email: str,
    config,
    *,
    to: list[str] | None,
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    html: bool = False,
) -> dict:
    token = load_token(account_email, config)
    payload = {"message": _message_body(subject, body, to, cc, bcc, html), "saveToSentItems": True}
    _post(client, token, "/me/sendmail", payload)
    return {"status": "sent"}


def create_draft(
    client: httpx.Client,
    account_email: str,
    config,
    *,
    to: list[str] | None,
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> dict:
    token = load_token(account_email, config)
    result = _post(client, token, "/me/messages", _message_body(subject, body, to, cc, bcc, False))
    return {"status": "drafted", "id": result.get("id")}


def reply_message(
    client: httpx.Client,
    account_email: str,
    config,
    *,
    item_id: str,
    body: str,
    reply_all: bool = False,
    html: bool = False,
) -> dict:
    token = load_token(account_email, config)
    endpoint = "replyall" if reply_all else "reply"
    _post(client, token, f"/me/messages/{item_id}/{endpoint}", {"comment": body})
    return {"status": "sent"}


def update_message(
    client: httpx.Client,
    account_email: str,
    config,
    *,
    item_id: str,
    is_read: bool | None = None,
    categories: list[str] | None = None,
) -> dict:
    if is_read is None and categories is None:
        raise OwaRestError("nothing to update")
    token = load_token(account_email, config)
    patch: dict[str, Any] = {}
    if is_read is not None:
        patch["isRead"] = is_read
    if categories is not None:
        patch["categories"] = categories
    _patch(client, token, f"/me/messages/{item_id}", patch)
    return {"status": "updated", "id": item_id}


def delete_message(client: httpx.Client, account_email: str, config, *, item_id: str, permanent: bool = False) -> dict:
    token = load_token(account_email, config)
    if permanent:
        _post(client, token, f"/me/messages/{item_id}/permanentDelete")
    else:
        _delete(client, token, f"/me/messages/{item_id}")
    return {"status": "deleted", "mode": "permanent" if permanent else "soft", "email_id": item_id}


def delete_by_sender(client: httpx.Client, account_email: str, config, *, sender: str, permanent: bool = False, scan: int = 200) -> dict:
    msgs = search_messages(client, account_email, config, query=f"from:{sender}", limit=scan)
    deleted = []
    for m in msgs:
        frm = (m.get("from") or {}).get("emailAddress", {}).get("address", "").lower()
        if frm == sender.lower():
            delete_message(client, account_email, config, item_id=m["id"], permanent=permanent)
            deleted.append(m["id"])
    return {
        "status": "deleted",
        "mode": "permanent" if permanent else "soft",
        "sender": sender,
        "deleted_count": len(deleted),
        "deleted_ids": deleted,
    }


def get_attachment(client: httpx.Client, account_email: str, config, *, email_id: str, attachment_id: str) -> dict:
    token = load_token(account_email, config)
    return _get(client, token, f"/me/messages/{email_id}/attachments/{attachment_id}")


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

_EVENT_SELECT = "id,subject,start,end,location,organizer,isAllDay,attendees,body,bodyPreview"


def list_events(client: httpx.Client, account_email: str, config, *, start_utc: str, end_utc: str, limit: int = 100) -> list[dict]:
    token = load_token(account_email, config)
    params = {
        "$select": _EVENT_SELECT,
        "$top": str(min(limit, 1000)),
        "startDateTime": start_utc,
        "endDateTime": end_utc,
    }
    return _paginate(client, token, "/me/calendarview", params, limit)


def list_calendars(client: httpx.Client, account_email: str, config) -> list[dict]:
    token = load_token(account_email, config)
    resp = _get(client, token, "/me/calendars", {"$select": "id,name"})
    return resp.get("value", [])


def get_event(client: httpx.Client, account_email: str, config, *, event_id: str) -> dict:
    token = load_token(account_email, config)
    return _get(client, token, f"/me/events/{event_id}", {"$select": _EVENT_SELECT})


def create_event(
    client: httpx.Client,
    account_email: str,
    config,
    *,
    subject: str,
    start: str,
    end: str,
    timezone: str,
    location: str | None = None,
    body: str | None = None,
    attendees: list[str] | None = None,
    is_all_day: bool = False,
) -> dict:
    token = load_token(account_email, config)
    payload: dict[str, Any] = {
        "subject": subject,
        "start": {"dateTime": start, "timeZone": timezone},
        "end": {"dateTime": end, "timeZone": timezone},
        "isAllDay": is_all_day,
    }
    if body:
        payload["body"] = {"contentType": "Text", "content": body}
    if location:
        payload["location"] = {"displayName": location}
    if attendees:
        payload["attendees"] = [{"emailAddress": {"address": a}, "type": "required"} for a in attendees]
    result = _post(client, token, "/me/events", payload)
    return {"status": "created", "id": result.get("id")}


def update_event(
    client: httpx.Client,
    account_email: str,
    config,
    *,
    event_id: str,
    subject: str | None = None,
    start: str | None = None,
    end: str | None = None,
    location: str | None = None,
    body: str | None = None,
    timezone: str | None = None,
) -> dict:
    token = load_token(account_email, config)
    patch: dict[str, Any] = {}
    tz = timezone or "UTC"
    if subject is not None:
        patch["subject"] = subject
    if start is not None:
        patch["start"] = {"dateTime": start, "timeZone": tz}
    if end is not None:
        patch["end"] = {"dateTime": end, "timeZone": tz}
    if location is not None:
        patch["location"] = {"displayName": location}
    if body is not None:
        patch["body"] = {"contentType": "Text", "content": body}
    if not patch:
        raise OwaRestError("nothing to update")
    _patch(client, token, f"/me/events/{event_id}", patch)
    return {"status": "updated", "id": event_id}


def delete_event(client: httpx.Client, account_email: str, config, *, event_id: str, send_cancellation: bool = True) -> dict:
    token = load_token(account_email, config)
    if send_cancellation:
        _post(client, token, f"/me/events/{event_id}/cancel", {"comment": ""})
    else:
        _delete(client, token, f"/me/events/{event_id}")
    return {"status": "deleted", "event_id": event_id}


def respond_event(
    client: httpx.Client,
    account_email: str,
    config,
    *,
    event_id: str,
    response: str = "accept",
    message: str | None = None,
) -> dict:
    _RESPONSE_ENDPOINTS = {
        "accept": "accept",
        "decline": "decline",
        "tentativelyAccept": "tentativelyaccept",
    }
    endpoint = _RESPONSE_ENDPOINTS.get(response)
    if endpoint is None:
        raise OwaRestError(f"unknown response: {response!r}; expected accept / decline / tentativelyAccept")
    token = load_token(account_email, config)
    payload: dict[str, Any] = {"sendResponse": True}
    if message:
        payload["comment"] = message
    _post(client, token, f"/me/events/{event_id}/{endpoint}", payload)
    return {"status": response}
