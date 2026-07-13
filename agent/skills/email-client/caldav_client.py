#!/usr/bin/env python3
"""Cross-provider CalDAV transport for the email-client calendar commands.

One module owns the protocol: auth header construction from the account's
provider profile, the WebDAV verbs over stdlib ``urllib`` (with manual
redirect handling, since iCloud bounces requests to per-user partition
hosts), RFC 6764 principal / calendar-home discovery, multistatus parsing,
and event lookup by iCalendar UID. All calendar network traffic funnels
through :func:`request` so tests can monkeypatch a single choke point.

Which providers have CalDAV, and where, is provider-profile knowledge: the
``caldav_url`` key in ``providers.py`` (Google, iCloud, Fastmail) or the
per-account ``caldav_url`` override in ``config.json`` for a generic host.
The auth style follows the profile's ``auth_strategy``: ``loopback-oauth``
(Google) sends the account's stored OAuth Bearer token with the same
transparent refresh mail uses; ``app-password`` providers send HTTP Basic
with the stored app password. ``device-flow`` (Microsoft) has no CalDAV
endpoint at all; those accounts are pointed at the microsoft skill.

Google's endpoint has a fixed layout (``{base}/{email}/events/``, no
discovery needed) and that is the only OAuth Bearer provider here, so the
layout choice keys off the auth kind.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import re
import sys
import typing as tp
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

import imap_client

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
REQUEST_TIMEOUT = 30
MAX_REDIRECTS = 5

NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}
CALENDAR_RESOURCETYPE = "{urn:ietf:params:xml:ns:caldav}calendar"

PRINCIPAL_BODY = '<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>'
HOME_BODY = '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><c:calendar-home-set/></d:prop></d:propfind>'
CALENDARS_BODY = (
    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    "<d:prop><d:displayname/><d:resourcetype/><c:supported-calendar-component-set/></d:prop></d:propfind>"
)
UID_QUERY = (
    '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    "<d:prop><d:getetag/><c:calendar-data/></d:prop>"
    '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
    '<c:prop-filter name="UID"><c:text-match collation="i;octet">{uid}</c:text-match></c:prop-filter>'
    "</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>"
)
TIME_RANGE_QUERY = (
    '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    "<d:prop><d:getetag/><c:calendar-data/></d:prop>"
    '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
    '<c:time-range start="{start}" end="{end}"/>'
    "</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>"
)


@dataclasses.dataclass(frozen=True)
class CalDavAccount:
    account: str
    user: str
    base_url: str
    auth: tp.Literal["bearer", "basic"]


@dataclasses.dataclass
class DavResource:
    href: str
    etag: str | None = None
    calendar_data: str | None = None
    displayname: str | None = None
    resourcetypes: set[str] = dataclasses.field(default_factory=set)
    components: set[str] = dataclasses.field(default_factory=set)
    principal_href: str | None = None
    home_href: str | None = None


@dataclasses.dataclass(frozen=True)
class CalendarInfo:
    id: str
    name: str
    url: str
    primary: bool


# -- account resolution -----------------------------------------------------


def _reauth_hint(account: str) -> str:
    return f"email-client auth add --account {account} --provider gmail --reauth"


def caldav_account(account: str | None) -> CalDavAccount:
    """Resolve an account into its CalDAV endpoint + auth style, or exit with a clear error."""
    acc = imap_client.resolve_account(account)
    name, profile = imap_client.account_profile(acc)
    strategy = profile["auth_strategy"]
    if strategy == "device-flow":
        sys.exit("no CalDAV calendar for this provider; use the microsoft skill for Outlook / Microsoft 365 calendars")
    base_url = str(profile["caldav_url"]).rstrip("/") if "caldav_url" in profile and profile["caldav_url"] else ""
    if not base_url:
        config_path = imap_client.account_dir(acc) / "config.json"
        sys.exit(f'provider {name!r} has no CalDAV endpoint; if it runs a CalDAV server, set "caldav_url" in {config_path}')
    if strategy == "loopback-oauth":
        tok = imap_client.load_token(acc)
        if tok is None:
            sys.exit(f"no token for account {acc!r}; run 'email-client auth add --account {acc}' first")
        # Google returns the granted scopes in the token response. If we can see
        # them and calendar isn't among them, this is an old mail-only auth: tell
        # the user to re-auth rather than making a call that will 403.
        scope = tok["scope"] if "scope" in tok else ""
        if scope and CALENDAR_SCOPE not in scope.split():
            sys.exit(
                f"account {acc!r} was authorized before calendar support (its token "
                f"lacks the calendar scope). Re-auth to grant it:\n  {_reauth_hint(acc)}"
            )
        auth: tp.Literal["bearer", "basic"] = "bearer"
    else:
        auth = "basic"
    return CalDavAccount(account=acc, user=imap_client.account_user(acc), base_url=base_url, auth=auth)


def _auth_header(ctx: CalDavAccount) -> str:
    if ctx.auth == "bearer":
        return f"Bearer {imap_client.get_access_token(ctx.account)}"
    raw = f"{ctx.user}:{imap_client.get_app_password(ctx.account)}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _refused_hint(ctx: CalDavAccount) -> str:
    if ctx.auth == "bearer":
        return f"The account's Google token was refused or lacks the calendar scope; re-auth with:\n  {_reauth_hint(ctx.account)}"
    return f"The app password was refused; generate a fresh one and re-run 'email-client auth add --account {ctx.account} --reauth'."


# -- HTTP (single choke point) ------------------------------------------------


def request(
    ctx: CalDavAccount,
    method: str,
    url: str,
    *,
    body: str | None = None,
    depth: str | None = None,
    content_type: str = "application/xml; charset=utf-8",
    extra_headers: dict[str, str] | None = None,
    allow_missing: bool = False,
) -> tuple[int, str, str]:
    """Issue one CalDAV request, following redirects, and return (status, body, final_url).

    Exits with an actionable message on failure; a 404 is returned (not fatal)
    when ``allow_missing`` is set so callers can fall back to a UID search.
    """
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        headers = {"Authorization": _auth_header(ctx)}
        if depth is not None:
            headers["Depth"] = depth
        data = None
        if body is not None:
            data = body.encode()
            headers["Content-Type"] = content_type
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(current, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace"), current
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 307, 308) and "Location" in e.headers:
                current = urllib.parse.urljoin(current, e.headers["Location"])
                continue
            detail = e.read().decode("utf-8", errors="replace")[:500]
            if e.code == 404 and allow_missing:
                return 404, detail, current
            if e.code in (401, 403):
                sys.exit(f"CalDAV refused the request (HTTP {e.code}). {_refused_hint(ctx)} (details: {detail[:300]})")
            sys.exit(f"CalDAV {method} failed (HTTP {e.code}): {detail}")
        except urllib.error.URLError as e:
            sys.exit(f"CalDAV {method} could not reach {urllib.parse.urlsplit(current).netloc}: {e.reason}")
    sys.exit(f"CalDAV {method} exceeded {MAX_REDIRECTS} redirects at {current}")


# -- multistatus parsing -------------------------------------------------------


def _child_href(prop: ET.Element, name: str) -> str | None:
    parent = prop.find(name, NS)
    if parent is None:
        return None
    href = parent.find("d:href", NS)
    return href.text if href is not None else None


def parse_multistatus(text: str) -> list[DavResource]:
    """Parse a multistatus body into per-resource records.

    Only ``propstat`` blocks whose status is 200 contribute props, so a 404
    half of a split response never masks the real value.
    """
    root = ET.fromstring(text)
    out: list[DavResource] = []
    for resp in root.findall("d:response", NS):
        href_el = resp.find("d:href", NS)
        record = DavResource(href=(href_el.text or "") if href_el is not None else "")
        for propstat in resp.findall("d:propstat", NS):
            status_el = propstat.find("d:status", NS)
            if status_el is not None and status_el.text and " 200 " not in status_el.text:
                continue
            prop = propstat.find("d:prop", NS)
            if prop is None:
                continue
            etag = prop.find("d:getetag", NS)
            if etag is not None and etag.text:
                record.etag = etag.text
            calendar_data = prop.find("c:calendar-data", NS)
            if calendar_data is not None and calendar_data.text:
                record.calendar_data = calendar_data.text
            displayname = prop.find("d:displayname", NS)
            if displayname is not None and displayname.text:
                record.displayname = displayname.text
            resourcetype = prop.find("d:resourcetype", NS)
            if resourcetype is not None:
                record.resourcetypes.update(child.tag for child in resourcetype)
            comp_set = prop.find("c:supported-calendar-component-set", NS)
            if comp_set is not None:
                record.components.update(comp.attrib["name"] for comp in comp_set.findall("c:comp", NS) if "name" in comp.attrib)
            principal = _child_href(prop, "d:current-user-principal")
            if principal:
                record.principal_href = principal
            home = _child_href(prop, "c:calendar-home-set")
            if home:
                record.home_href = home
        out.append(record)
    return out


# -- discovery + calendar collections -----------------------------------------


def _discovered_home_url(ctx: CalDavAccount) -> str:
    _, text, final = request(ctx, "PROPFIND", ctx.base_url + "/", body=PRINCIPAL_BODY, depth="0")
    principal = next((rec.principal_href for rec in parse_multistatus(text) if rec.principal_href), None)
    if principal is None:
        sys.exit(f"CalDAV discovery failed: no current-user-principal at {ctx.base_url}")
    principal_url = urllib.parse.urljoin(final, principal)
    _, text, final = request(ctx, "PROPFIND", principal_url, body=HOME_BODY, depth="0")
    home = next((rec.home_href for rec in parse_multistatus(text) if rec.home_href), None)
    if home is None:
        sys.exit(f"CalDAV discovery failed: no calendar-home-set at {principal_url}")
    return urllib.parse.urljoin(final, home)


def home_url(ctx: CalDavAccount) -> str:
    if ctx.auth == "bearer":
        return f"{ctx.base_url}/{urllib.parse.quote(ctx.user, safe='@')}/"
    return _discovered_home_url(ctx)


def _calendar_id(ctx: CalDavAccount, url: str) -> str:
    path = urllib.parse.urlsplit(url).path
    if ctx.auth == "bearer":
        match = re.search(r"/caldav/v2/([^/]+)/", path)
        if match:
            return urllib.parse.unquote(match.group(1))
    segments = [urllib.parse.unquote(segment) for segment in path.split("/") if segment]
    return segments[-1] if segments else url


def list_calendars(ctx: CalDavAccount) -> list[CalendarInfo]:
    """The account's VEVENT calendar collections, primary first-classed."""
    home = home_url(ctx)
    _, text, final = request(ctx, "PROPFIND", home, body=CALENDARS_BODY, depth="1")
    infos: list[CalendarInfo] = []
    for record in parse_multistatus(text):
        if CALENDAR_RESOURCETYPE not in record.resourcetypes:
            continue
        if record.components and "VEVENT" not in record.components:
            continue
        url = urllib.parse.urljoin(final, record.href)
        if not url.endswith("/"):
            url += "/"
        cal_id = _calendar_id(ctx, url)
        infos.append(CalendarInfo(id=cal_id, name=record.displayname or cal_id, url=url, primary=False))
    if not infos:
        sys.exit(f"no calendar collections found under {home}")
    primary_id = ctx.user if ctx.auth == "bearer" else infos[0].id
    return [dataclasses.replace(info, primary=info.id == primary_id) for info in infos]


def collection_url(ctx: CalDavAccount, calendar_id: str) -> str:
    """Events-collection URL for a calendar id ('primary' resolves per provider)."""
    if ctx.auth == "bearer":
        # Google: 'primary' is keyed by the account email; any other id is a
        # Google calendar id (e.g. ...@group.calendar.google.com) used verbatim.
        cal = ctx.user if calendar_id == "primary" else calendar_id
        return f"{ctx.base_url}/{urllib.parse.quote(cal, safe='@')}/events/"
    calendars = list_calendars(ctx)
    if calendar_id == "primary":
        return next(info.url for info in calendars if info.primary)
    for info in calendars:
        if calendar_id in (info.id, info.name):
            return info.url
    sys.exit(f"unknown calendar {calendar_id!r}; known: {[info.id for info in calendars]}")


# -- event access ---------------------------------------------------------------


def _caldav_stamp(when: dt.datetime) -> str:
    return when.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def report_events(ctx: CalDavAccount, calendar_id: str, start: dt.datetime, end: dt.datetime) -> list[str]:
    """calendar-query REPORT for events overlapping [start, end); one ics text per resource."""
    collection = collection_url(ctx, calendar_id)
    body = TIME_RANGE_QUERY.format(start=_caldav_stamp(start), end=_caldav_stamp(end))
    _, text, _ = request(ctx, "REPORT", collection, body=body, depth="1")
    return [record.calendar_data for record in parse_multistatus(text) if record.calendar_data]


def find_event(ctx: CalDavAccount, calendar_id: str, uid: str) -> tuple[str, str]:
    """Return (event_url, ics_text) for an event UID.

    Tries the conventional ``{uid}.ics`` resource name first (always true for
    events this skill created, and for Google), then falls back to a UID
    calendar-query REPORT since CalDAV does not guarantee resource naming.
    """
    collection = collection_url(ctx, calendar_id)
    direct = collection + urllib.parse.quote(uid, safe="") + ".ics"
    status, text, final = request(ctx, "GET", direct, allow_missing=True)
    if status == 200:
        return final, text
    body = UID_QUERY.format(uid=xml_escape(uid))
    _, text, final = request(ctx, "REPORT", collection, body=body, depth="1")
    for record in parse_multistatus(text):
        if record.calendar_data and record.href:
            return urllib.parse.urljoin(final, record.href), record.calendar_data
    sys.exit(f"event {uid!r} not found in calendar {calendar_id!r}")
