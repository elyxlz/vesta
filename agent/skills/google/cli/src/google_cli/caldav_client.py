#!/usr/bin/env python3
"""CalDAV transport for Google Calendar.

The google skill rides Mozilla Thunderbird's published public OAuth client. That
client's Google Cloud project has the **Calendar REST API disabled**, so every
``calendar/v3`` call 403s with ``accessNotConfigured`` — we do not own that
project and cannot enable it. CalDAV is the way out: it is how Thunderbird itself
talks to Google Calendar, it rides the SAME ``.../auth/calendar`` OAuth scope, and
it bypasses the disabled REST API entirely (verified: a Bearer-token PROPFIND to
``apidata.googleusercontent.com/caldav/v2`` returns 207).

This module is the thin HTTP layer: it does the OAuth Bearer plumbing, issues the
CalDAV verbs (PROPFIND / REPORT / PUT / DELETE / GET) over stdlib ``urllib``, and
parses ``multistatus`` XML. The iCalendar parse/emit and the command surface live
in :mod:`calendar`. All calendar traffic funnels through :func:`request` so tests
can monkeypatch a single choke point.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree as ET

from . import auth
from .config import Config

CALDAV_BASE = "https://apidata.googleusercontent.com/caldav/v2"

# XML namespaces used in CalDAV multistatus responses.
NS = {
    "d": "DAV:",
    "c": "urn:ietf:params:xml:ns:caldav",
}

# Where the resolved account email is cached so "primary" -> collection path does
# not cost a Gmail getProfile call on every command (the monitor lists every 45s).
_EMAIL_CACHE_FILENAME = "account_email.txt"


class CalDavError(RuntimeError):
    """A CalDAV request failed. Carries an agent/user-actionable message."""


def _credentials(config: Config):
    """Fresh OAuth credentials (transparently refreshed) for the CalDAV Bearer."""
    return auth.get_credentials(config.token_file, config.credentials_file, config.scopes)


def account_email(config: Config, *, creds=None) -> str:
    """Resolve (and cache) the authenticated account's email.

    The primary calendar's CalDAV collection is keyed by the account email, so we
    need it to build the ``primary`` path. Cached in the data dir because it never
    changes for a single-account skill and the monitor would otherwise re-fetch it
    every poll.
    """
    cache = config.data_dir / _EMAIL_CACHE_FILENAME
    if cache.exists():
        value = cache.read_text().strip()
        if value:
            return value
    creds = creds or _credentials(config)
    email = auth.get_user_email(creds)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(email)
    return email


def collection_url(config: Config, calendar_id: str = "primary") -> str:
    """Return the events-collection URL for a calendar id.

    ``primary`` maps to the account email; any other id is a Google calendar id
    (e.g. ``...@group.calendar.google.com``) used verbatim as the path segment.
    """
    cal = account_email(config) if calendar_id in (None, "primary") else calendar_id
    return f"{CALDAV_BASE}/{urllib.parse.quote(cal, safe='@')}/events/"


def event_url(config: Config, calendar_id: str, uid: str) -> str:
    """Return the ``.ics`` resource URL for a single event id (its iCal UID)."""
    return collection_url(config, calendar_id) + urllib.parse.quote(uid, safe="") + ".ics"


def home_url(config: Config, calendar_id: str = "primary") -> str:
    """Return the calendar-home collection URL (parent of the events collection)."""
    cal = account_email(config) if calendar_id in (None, "primary") else calendar_id
    return f"{CALDAV_BASE}/{urllib.parse.quote(cal, safe='@')}/"


def request(
    config: Config,
    method: str,
    url: str,
    *,
    body: str | None = None,
    depth: str | None = None,
    content_type: str = "application/xml; charset=utf-8",
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Issue one CalDAV request and return ``(http_status, response_text)``.

    Single choke point for all calendar traffic. Raises :class:`CalDavError` with
    an actionable message on failure — 401/403 point the caller at re-auth.
    """
    creds = _credentials(config)
    headers = {"Authorization": f"Bearer {creds.token}"}
    if depth is not None:
        headers["Depth"] = depth
    data = None
    if body is not None:
        data = body.encode("utf-8")
        headers["Content-Type"] = content_type
    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return getattr(resp, "status", 200), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(e)
        if e.code in (401, 403):
            raise CalDavError(
                f"Google Calendar (CalDAV) refused the request (HTTP {e.code}). "
                "The account's token is missing or lacks the calendar scope. "
                "Re-authenticate with 'google auth login'. "
                f"(details: {detail[:300]})"
            )
        if e.code == 404:
            raise CalDavError(f"CalDAV resource not found (HTTP 404): {url}")
        raise CalDavError(f"CalDAV {method} failed (HTTP {e.code}): {detail[:500]}")
    except urllib.error.URLError as e:
        raise CalDavError(f"CalDAV {method} could not reach Google: {e.reason}")


# -- multistatus parsing -------------------------------------------------


def parse_multistatus(text: str) -> list[dict]:
    """Parse a CalDAV ``multistatus`` body into per-resource records.

    Returns a list of ``{"href", "etag", "calendar_data", "resourcetypes",
    "displayname"}`` dicts (missing fields are ``None``). Only ``propstat`` blocks
    whose status is 200 contribute props, so a 404 half of a split response never
    masks the real value.
    """
    root = ET.fromstring(text)
    out: list[dict] = []
    for resp in root.findall("d:response", NS):
        href_el = resp.find("d:href", NS)
        record: dict = {
            "href": href_el.text if href_el is not None else None,
            "etag": None,
            "calendar_data": None,
            "displayname": None,
            "resourcetypes": set(),
        }
        for propstat in resp.findall("d:propstat", NS):
            status_el = propstat.find("d:status", NS)
            if status_el is not None and status_el.text and " 200 " not in status_el.text:
                continue
            prop = propstat.find("d:prop", NS)
            if prop is None:
                continue
            etag = prop.find("d:getetag", NS)
            if etag is not None and etag.text:
                record["etag"] = etag.text
            cdata = prop.find("c:calendar-data", NS)
            if cdata is not None and cdata.text:
                record["calendar_data"] = cdata.text
            dname = prop.find("d:displayname", NS)
            if dname is not None and dname.text:
                record["displayname"] = dname.text
            rtype = prop.find("d:resourcetype", NS)
            if rtype is not None:
                for child in rtype:
                    record["resourcetypes"].add(child.tag)
        out.append(record)
    return out
