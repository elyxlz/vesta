"""Microsoft Teams over Graph, with the same two-source auth as mail.

Teams data lives only behind Microsoft Graph (``graph.microsoft.com``), so both
"backends" here run the *same* Graph transport and differ only in token source,
mirroring the mail split of a clean device-flow path vs a locked-tenant browser
capture:

* **graph**: a device-flow token minted by MSAL for the Teams scopes. Requested
  once with ``microsoft auth teams-login`` (separate from the mail login so a
  mail-only account never gets a Teams consent prompt).
* **owa-rest** (the fallback path, kept named for a uniform ``--backend``): a
  Graph-audience token captured from a signed-in ``teams.microsoft.com`` session
  in the agent's own browser, for tenants that block the CLI's app registration.

``graph_token`` raises :class:`backend.GraphUnavailable` when no device token is
available, so ``backend.run(AUTO, ...)`` falls through to the captured token
exactly like the mail dispatcher.

Teams tokens are recorded per account under ``teams_tokens/{email}.json`` (same
shape as the OWA REST markers): ``{"source": "device"}`` after a device login, or
``{"source": "browser", "token", "expires_at"}`` after a capture/paste. The
marker set is what the monitor and ``list_accounts`` enumerate.
"""

from __future__ import annotations

import json
import pathlib as pl
import time
from typing import Any

import httpx

from . import auth, backend
from .settings import DEFAULT_CLIENT_ID

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Delegated Graph scopes for Teams. Every one is user-consentable (no admin
# consent), so `auth teams-login` works for non-admins. Chat.ReadWrite subsumes
# read + send + create-chat + edit; ChannelMessage.Send covers channel posts and
# replies. Reading channel *messages* needs the admin-only ChannelMessage.Read.All,
# deliberately left out so it never blocks the consent bundle; grant it on your own
# app registration (MICROSOFT_MCP_CLIENT_ID) if you need channel reads.
TEAMS_SCOPES = [
    "https://graph.microsoft.com/Chat.ReadWrite",
    "https://graph.microsoft.com/ChannelMessage.Send",
    "https://graph.microsoft.com/Team.ReadBasic.All",
    "https://graph.microsoft.com/Channel.ReadBasic.All",
    "https://graph.microsoft.com/Presence.ReadWrite",
]

# Chats list: only these two $expand values are supported, and the single
# supported $orderby is on lastMessagePreview (desc only). $top caps at 50.
_CHATS_EXPAND = "members,lastMessagePreview"
_CHATS_ORDERBY = "lastMessagePreview/createdDateTime desc"
_MAX_TOP = 50

_TOKEN_SUBDIR = "teams_tokens"
_TOKEN_EXPIRY_MARGIN = 60  # seconds: treat a token as expired this many seconds early


class TeamsError(RuntimeError):
    """A Teams Graph call returned an unexpected error."""


class TeamsNoToken(TeamsError):
    """No usable Teams token is on disk; the user must run auth teams-login/teams-capture."""


# ---------------------------------------------------------------------------
# Token markers (mirrors owa_rest's per-account token files)
# ---------------------------------------------------------------------------


def _token_path(account_email: str, config) -> pl.Path:
    return pl.Path(config.data_dir) / _TOKEN_SUBDIR / f"{account_email}.json"


def _read_marker(account_email: str, config) -> dict | None:
    try:
        return json.loads(_token_path(account_email, config).read_text())
    except FileNotFoundError:
        return None


def _source(marker: dict) -> str:
    return marker["source"] if "source" in marker else "browser"


def list_accounts(config) -> list[str]:
    """Email addresses that have a Teams token marker on disk (device or browser)."""
    token_dir = pl.Path(config.data_dir) / _TOKEN_SUBDIR
    if not token_dir.is_dir():
        return []
    return sorted(p.stem for p in token_dir.glob("*.json"))


def mark_device_account(account_email: str, config) -> None:
    """Record that this account authenticates Teams via device-flow (tokens come from MSAL)."""
    p = _token_path(account_email, config)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"source": "device"}))


def save_token(account_email: str, config, *, token: str, expires_at: float, source: str = "browser") -> None:
    """Persist a captured token. Never log the token value."""
    p = _token_path(account_email, config)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"source": source, "token": token, "expires_at": expires_at}))


def has_token(account_email: str, config) -> bool:
    """True (network-free) if this account can produce a Teams token: a device account still in
    the MSAL cache, or a browser-captured token that has not expired."""
    marker = _read_marker(account_email, config)
    if marker is None:
        return False
    if _source(marker) == "device":
        try:
            return auth.account_in_cache(config.cache_file, account_email, client_id=DEFAULT_CLIENT_ID)
        except Exception:
            return False
    try:
        return float(marker["expires_at"]) > time.time() + _TOKEN_EXPIRY_MARGIN
    except (KeyError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------


def graph_token(config, account_email: str) -> str:
    """Mint a Teams Graph token from MSAL silently. Raise GraphUnavailable when none exists so
    the AUTO dispatcher falls back to the captured token."""
    try:
        account_id = auth.get_account_id_by_email(account_email, config.cache_file)
    except ValueError as exc:
        raise backend.GraphUnavailable(str(exc)) from exc
    token = auth.get_token_silent(config.cache_file, TEAMS_SCOPES, account_id=account_id, client_id=DEFAULT_CLIENT_ID)
    if not token:
        raise backend.GraphUnavailable(f"No Teams token for {account_email}. Run: microsoft auth teams-login")
    return token


def captured_token(config, account_email: str) -> str:
    """Return the browser-captured Teams token or raise TeamsNoToken."""
    marker = _read_marker(account_email, config)
    if marker is None or _source(marker) != "browser":
        raise TeamsNoToken(f"No captured Teams token for {account_email}. Run: microsoft auth teams-capture --account {account_email}")
    if float(marker["expires_at"]) <= time.time() + _TOKEN_EXPIRY_MARGIN:
        raise TeamsNoToken(f"Captured Teams token expired for {account_email}. Run: microsoft auth teams-capture --account {account_email}")
    return marker["token"]


def resolve_token(config, account_email: str) -> str:
    """Return any usable Teams token (device first, then captured). Used by the monitor."""
    marker = _read_marker(account_email, config)
    if marker is None:
        raise TeamsNoToken(f"No Teams token for {account_email}. Run: microsoft auth teams-login")
    if _source(marker) == "device":
        return graph_token(config, account_email)
    return captured_token(config, account_email)


# ---------------------------------------------------------------------------
# HTTP transport (Graph is already camelCase; no key-case adapter needed)
# ---------------------------------------------------------------------------


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _get(client: httpx.Client, token: str, path: str, params: dict | None = None) -> Any:
    resp = client.get(f"{GRAPH_BASE}{path}", headers=_headers(token), params=params)
    resp.raise_for_status()
    return resp.json()


def _post(client: httpx.Client, token: str, path: str, body: Any = None) -> Any:
    resp = client.post(f"{GRAPH_BASE}{path}", headers={**_headers(token), "Content-Type": "application/json"}, json=body)
    resp.raise_for_status()
    if not resp.content:
        return {}
    return resp.json()


def _paginate(client: httpx.Client, token: str, path: str, params: dict, limit: int) -> list[Any]:
    """Collect items following @odata.nextLink until ``limit`` reached."""
    results: list[Any] = []
    resp = _get(client, token, path, params)
    while True:
        results.extend(resp["value"] if "value" in resp else [])
        if len(results) >= limit:
            break
        next_link = resp["@odata.nextLink"] if "@odata.nextLink" in resp else None
        if not next_link:
            break
        resp = _get(client, token, next_link.replace(GRAPH_BASE, ""))
    return results[:limit]


def _message_body(content: str, html: bool) -> dict:
    return {"body": {"contentType": "html" if html else "text", "content": content}}


def _my_id(client: httpx.Client, token: str) -> str:
    """The signed-in user's directory id (needed for the presence-set endpoint, which has no /me form)."""
    me = _get(client, token, "/me", {"$select": "id"})
    return me["id"]


# ---------------------------------------------------------------------------
# Chats
# ---------------------------------------------------------------------------


def list_chats(client: httpx.Client, token: str, *, limit: int = 20) -> list[dict]:
    params = {
        "$expand": _CHATS_EXPAND,
        "$orderby": _CHATS_ORDERBY,
        "$top": str(min(limit, _MAX_TOP)),
    }
    return _paginate(client, token, "/me/chats", params, limit)


def list_chat_messages(client: httpx.Client, token: str, *, chat_id: str, limit: int = 20) -> list[dict]:
    params = {"$top": str(min(limit, _MAX_TOP))}
    return _paginate(client, token, f"/chats/{chat_id}/messages", params, limit)


def send_chat_message(client: httpx.Client, token: str, *, chat_id: str, body: str, html: bool = False) -> dict:
    result = _post(client, token, f"/chats/{chat_id}/messages", _message_body(body, html))
    return {"status": "sent", "chat_id": chat_id, "id": result["id"] if "id" in result else None}


def start_chat(
    client: httpx.Client, token: str, *, members: list[str], body: str | None = None, topic: str | None = None, html: bool = False
) -> dict:
    """Create a one-on-one or group chat. The caller is added automatically; a topic is allowed
    only for group chats (3+ members)."""
    self_email = _get(client, token, "/me", {"$select": "userPrincipalName"})["userPrincipalName"]
    everyone = list(dict.fromkeys([self_email, *members]))
    chat_type = "oneOnOne" if len(everyone) == 2 else "group"
    payload: dict[str, Any] = {
        "chatType": chat_type,
        "members": [
            {
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "roles": ["owner"],
                "user@odata.bind": f"{GRAPH_BASE}/users('{addr}')",
            }
            for addr in everyone
        ],
    }
    if topic and chat_type == "group":
        payload["topic"] = topic
    chat = _post(client, token, "/chats", payload)
    chat_id = chat["id"]
    if body:
        send_chat_message(client, token, chat_id=chat_id, body=body, html=html)
    return {"status": "created", "id": chat_id, "chat_type": chat_type}


# ---------------------------------------------------------------------------
# Teams and channels
# ---------------------------------------------------------------------------


def list_teams(client: httpx.Client, token: str) -> list[dict]:
    # /me/joinedTeams supports no OData query params.
    resp = _get(client, token, "/me/joinedTeams")
    return resp["value"] if "value" in resp else []


def list_channels(client: httpx.Client, token: str, *, team_id: str) -> list[dict]:
    resp = _get(client, token, f"/teams/{team_id}/channels", {"$select": "id,displayName,description,membershipType"})
    return resp["value"] if "value" in resp else []


def list_channel_messages(client: httpx.Client, token: str, *, team_id: str, channel_id: str, limit: int = 20) -> list[dict]:
    """Read channel messages. Requires the admin-consent ChannelMessage.Read.All scope, so on the
    default client this raises a permission error unless an admin has granted it."""
    params = {"$top": str(min(limit, _MAX_TOP))}
    return _paginate(client, token, f"/teams/{team_id}/channels/{channel_id}/messages", params, limit)


def post_channel_message(client: httpx.Client, token: str, *, team_id: str, channel_id: str, body: str, html: bool = False) -> dict:
    result = _post(client, token, f"/teams/{team_id}/channels/{channel_id}/messages", _message_body(body, html))
    return {"status": "posted", "id": result["id"] if "id" in result else None}


def reply_channel_message(
    client: httpx.Client, token: str, *, team_id: str, channel_id: str, message_id: str, body: str, html: bool = False
) -> dict:
    result = _post(client, token, f"/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies", _message_body(body, html))
    return {"status": "replied", "id": result["id"] if "id" in result else None}


# ---------------------------------------------------------------------------
# Presence
# ---------------------------------------------------------------------------

# The valid availability/activity pairs Graph accepts for setUserPreferredPresence.
_PRESENCE_ACTIVITY = {
    "Available": "Available",
    "Busy": "Busy",
    "DoNotDisturb": "DoNotDisturb",
    "BeRightBack": "BeRightBack",
    "Away": "Away",
    "Offline": "OffWork",
}


def get_presence(client: httpx.Client, token: str) -> dict:
    return _get(client, token, "/me/presence")


def set_presence(client: httpx.Client, token: str, *, availability: str, expires: str | None = None) -> dict:
    if availability not in _PRESENCE_ACTIVITY:
        raise TeamsError(f"unknown availability {availability!r}; expected one of {', '.join(_PRESENCE_ACTIVITY)}")
    payload: dict[str, Any] = {"availability": availability, "activity": _PRESENCE_ACTIVITY[availability]}
    if expires:
        payload["expirationDuration"] = expires
    _post(client, token, f"/users/{_my_id(client, token)}/presence/setUserPreferredPresence", payload)
    return {"status": "set", "availability": availability}


def clear_presence(client: httpx.Client, token: str) -> dict:
    _post(client, token, f"/users/{_my_id(client, token)}/presence/clearUserPreferredPresence")
    return {"status": "cleared"}
