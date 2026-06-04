"""Reverse-engineered fallback backend: Exchange Web Services (EWS) over a
first-party bearer token.

This is the path the CLI falls back to when the official Microsoft Graph
surface is unavailable because of tenant permissions (third-party apps blocked,
Graph disabled for the app, or a delegated scope the registered app was never
granted).

Why EWS, and why it survives a locked-down company tenant:

* It authenticates with a bearer token for the ``outlook.office.com`` resource
  minted by the first-party "Microsoft Office" public client (see
  ``settings.owa_client_id``). That client is trusted tenant-wide, so it is not
  stopped by the "block third-party apps" admin control that blocks a custom
  Azure registration.
* EWS is the same protocol Outlook on the web speaks underneath: the browser's
  ``/owa/service.svc`` endpoint is a JSON skin over these exact operations
  (FindItem, GetItem, CreateItem, ...). A tenant cannot disable EWS without also
  breaking Outlook/Exchange access for its own users.

If a tenant ever disables EWS itself, the documented escape hatch (see the PR /
SETUP notes) is to drive a headless browser against Outlook on the web, capture
the live ``service.svc`` session, and replay those calls. That is strictly more
fragile, so EWS is the default.

Every function here returns dictionaries shaped like the Microsoft Graph
responses the rest of the CLI already consumes, so this backend is a drop-in
substitute for the Graph path.
"""

from __future__ import annotations

import logging
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as _xml_escape

import httpx

from .auth import get_token
from .settings import MicrosoftSettings

logger = logging.getLogger(__name__)

EWS_ENDPOINT = "https://outlook.office365.com/EWS/Exchange.asmx"
# Scope the first-party client is pre-authorized for on the outlook.office.com
# resource. EWS.AccessAsUser.All is what the EWS endpoint honors.
OWA_SCOPES = ["https://outlook.office.com/EWS.AccessAsUser.All"]

_NS = {
    "s": "http://schemas.xmlsoap.org/soap/envelope/",
    "m": "http://schemas.microsoft.com/exchange/services/2006/messages",
    "t": "http://schemas.microsoft.com/exchange/services/2006/types",
}

_DISTINGUISHED_FOLDERS = {
    "inbox": "inbox",
    "sentitems": "sentitems",
    "sent": "sentitems",
    "drafts": "drafts",
    "deleteditems": "deleteditems",
    "deleted": "deleteditems",
    "junkemail": "junkemail",
    "junk": "junkemail",
    "archive": "archive",
    "calendar": "calendar",
}


class OwaError(RuntimeError):
    """An EWS call returned a SOAP fault or an error ResponseClass."""


def _token(cache_file, settings: MicrosoftSettings, account_id: str | None) -> str:
    return get_token(cache_file, OWA_SCOPES, settings, account_id=account_id, client_id=settings.owa_client_id)


def _esc(value: Any) -> str:
    return _xml_escape("" if value is None else str(value))


def _envelope(inner: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"'
        ' xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"'
        ' xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages">'
        "<soap:Header><t:RequestServerVersion Version=\"Exchange2013\"/></soap:Header>"
        f"<soap:Body>{inner}</soap:Body></soap:Envelope>"
    )


def call(
    client: httpx.Client,
    cache_file,
    settings: MicrosoftSettings,
    inner_xml: str,
    account_id: str | None = None,
) -> ET.Element:
    """POST a SOAP body to the EWS endpoint, return the parsed <s:Body> element.

    Raises httpx.HTTPStatusError on 401/403 (so the dispatcher treats it as a
    permission failure, consistent with the Graph path) and OwaError on a SOAP
    fault.
    """
    token = _token(cache_file, settings, account_id)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "text/xml; charset=utf-8"}
    resp = client.post(EWS_ENDPOINT, headers=headers, content=_envelope(inner_xml).encode("utf-8"))
    if resp.status_code in (401, 403):
        resp.raise_for_status()
    if resp.status_code != 200:
        raise OwaError(f"EWS HTTP {resp.status_code}: {resp.text[:300]}")
    root = ET.fromstring(resp.text)
    body = root.find("s:Body", _NS)
    fault = body.find("s:Fault", _NS) if body is not None else None
    if fault is not None:
        msg = fault.findtext("faultstring") or "SOAP fault"
        raise OwaError(msg)
    return body


def _check_response_messages(body: ET.Element) -> list[ET.Element]:
    """Return every *ResponseMessage element, raising OwaError on any error class."""
    msgs: list[ET.Element] = []
    for rm in body.iter():
        if rm.tag.endswith("ResponseMessage") and "ResponseClass" in rm.attrib:
            cls = rm.attrib["ResponseClass"]
            if cls == "Error":
                text = rm.findtext("m:MessageText", default="", namespaces=_NS) or rm.findtext(
                    "m:ResponseCode", default="EWS error", namespaces=_NS
                )
                raise OwaError(text)
            msgs.append(rm)
    return msgs


# ---------------------------------------------------------------------------
# XML element -> Graph-shaped dict normalization
# ---------------------------------------------------------------------------
def _text(el: ET.Element | None, path: str) -> str | None:
    if el is None:
        return None
    return el.findtext(path, namespaces=_NS)


def _mailbox_dict(el: ET.Element | None) -> dict[str, Any]:
    """<t:From>/<t:Organizer> wrap a <t:Mailbox>; recipients ARE mailboxes."""
    if el is None:
        return {"emailAddress": {"address": "", "name": ""}}
    mb = el.find("t:Mailbox", _NS)
    mb = mb if mb is not None else el
    return {
        "emailAddress": {
            "address": _text(mb, "t:EmailAddress") or "",
            "name": _text(mb, "t:Name") or "",
        }
    }


def _recipient_list(el: ET.Element | None) -> list[dict[str, Any]]:
    if el is None:
        return []
    return [
        {"emailAddress": {"address": _text(mb, "t:EmailAddress") or "", "name": _text(mb, "t:Name") or ""}}
        for mb in el.findall("t:Mailbox", _NS)
    ]


def _item_id(el: ET.Element | None) -> dict[str, str]:
    iid = el.find("t:ItemId", _NS) if el is not None else None
    if iid is None:
        return {}
    return {"id": iid.attrib.get("Id"), "changeKey": iid.attrib.get("ChangeKey")}


def norm_message(item: ET.Element) -> dict[str, Any]:
    iid = _item_id(item)
    out: dict[str, Any] = {
        "id": iid.get("id"),
        "changeKey": iid.get("changeKey"),
        "subject": _text(item, "t:Subject"),
        "receivedDateTime": _text(item, "t:DateTimeReceived"),
        "sentDateTime": _text(item, "t:DateTimeSent"),
        "isRead": (_text(item, "t:IsRead") or "false").lower() == "true",
        "hasAttachments": (_text(item, "t:HasAttachments") or "false").lower() == "true",
    }
    conv = item.find("t:ConversationId", _NS)
    if conv is not None:
        out["conversationId"] = conv.attrib.get("Id")
    frm = item.find("t:From", _NS)
    if frm is not None:
        out["from"] = _mailbox_dict(frm)
    to = item.find("t:ToRecipients", _NS)
    if to is not None:
        out["toRecipients"] = _recipient_list(to)
    cc = item.find("t:CcRecipients", _NS)
    if cc is not None:
        out["ccRecipients"] = _recipient_list(cc)
    body = item.find("t:Body", _NS)
    if body is not None:
        out["body"] = {"contentType": body.attrib.get("BodyType", "Text"), "content": body.text or ""}
    cats = item.find("t:Categories", _NS)
    if cats is not None:
        out["categories"] = [s.text for s in cats.findall("t:String", _NS) if s.text]
    preview = _text(item, "t:Preview")
    if preview:
        out["bodyPreview"] = preview
    return out


def norm_event(item: ET.Element) -> dict[str, Any]:
    iid = _item_id(item)
    out: dict[str, Any] = {
        "id": iid.get("id"),
        "changeKey": iid.get("changeKey"),
        "subject": _text(item, "t:Subject"),
        "isAllDay": (_text(item, "t:IsAllDayEvent") or "false").lower() == "true",
    }
    start = _text(item, "t:Start")
    end = _text(item, "t:End")
    if start:
        out["start"] = {"dateTime": start, "timeZone": "UTC"}
    if end:
        out["end"] = {"dateTime": end, "timeZone": "UTC"}
    loc = _text(item, "t:Location")
    if loc:
        out["location"] = {"displayName": loc}
    org = item.find("t:Organizer", _NS)
    if org is not None:
        out["organizer"] = _mailbox_dict(org)
    body = item.find("t:Body", _NS)
    if body is not None:
        out["body"] = {"contentType": body.attrib.get("BodyType", "Text"), "content": body.text or ""}
    attendees = []
    for block in ("t:RequiredAttendees", "t:OptionalAttendees"):
        b = item.find(block, _NS)
        if b is not None:
            for att in b.findall("t:Attendee", _NS):
                attendees.append(_mailbox_dict(att))
    if attendees:
        out["attendees"] = attendees
    return out


# ---------------------------------------------------------------------------
# Shared request fragments
# ---------------------------------------------------------------------------
def _distinguished(name: str | None) -> str:
    key = (name or "inbox").casefold()
    dist = _DISTINGUISHED_FOLDERS.get(key, key)
    return f'<t:DistinguishedFolderId Id="{_esc(dist)}"/>'


_MESSAGE_PROPS = (
    '<t:FieldURI FieldURI="item:Subject"/>'
    '<t:FieldURI FieldURI="item:DateTimeReceived"/>'
    '<t:FieldURI FieldURI="item:DateTimeSent"/>'
    '<t:FieldURI FieldURI="item:HasAttachments"/>'
    '<t:FieldURI FieldURI="message:IsRead"/>'
    '<t:FieldURI FieldURI="message:From"/>'
    '<t:FieldURI FieldURI="message:ToRecipients"/>'
    '<t:FieldURI FieldURI="message:CcRecipients"/>'
    '<t:FieldURI FieldURI="item:Categories"/>'
    '<t:FieldURI FieldURI="item:ConversationId"/>'
)


def _recipients_xml(tag: str, addrs: list[str] | None) -> str:
    if not addrs:
        return ""
    boxes = "".join(f"<t:Mailbox><t:EmailAddress>{_esc(a)}</t:EmailAddress></t:Mailbox>" for a in addrs)
    return f"<t:{tag}>{boxes}</t:{tag}>"


def _message_xml(subject, body, to, cc, bcc, html, extra="") -> str:
    body_type = "HTML" if html else "Text"
    return (
        "<t:Message>"
        f"<t:Subject>{_esc(subject)}</t:Subject>"
        f'<t:Body BodyType="{body_type}">{_esc(body)}</t:Body>'
        f"{extra}"
        f"{_recipients_xml('ToRecipients', to)}"
        f"{_recipients_xml('CcRecipients', cc)}"
        f"{_recipients_xml('BccRecipients', bcc)}"
        "</t:Message>"
    )


# ---------------------------------------------------------------------------
# Mail: read
# ---------------------------------------------------------------------------
def list_messages(client, cache_file, settings, *, account_id, folder="inbox", limit=10):
    inner = (
        '<m:FindItem Traversal="Shallow">'
        '<m:ItemShape><t:BaseShape>IdOnly</t:BaseShape>'
        f'<t:AdditionalProperties>{_MESSAGE_PROPS}</t:AdditionalProperties></m:ItemShape>'
        '<m:SortOrder><t:FieldOrder Order="Descending">'
        '<t:FieldURI FieldURI="item:DateTimeReceived"/></t:FieldOrder></m:SortOrder>'
        f'<m:IndexedPageItemView MaxEntriesReturned="{min(limit,100)}" Offset="0" BasePoint="Beginning"/>'
        f'<m:ParentFolderIds>{_distinguished(folder)}</m:ParentFolderIds>'
        '</m:FindItem>'
    )
    body = call(client, cache_file, settings, inner, account_id)
    _check_response_messages(body)
    return [norm_message(m) for m in body.iter() if m.tag.endswith("}Message")]


def search_messages(client, cache_file, settings, *, account_id, query, folder=None, limit=10):
    # AQS via QueryString, the same mechanism the OWA search box uses.
    inner = (
        '<m:FindItem Traversal="Shallow">'
        '<m:ItemShape><t:BaseShape>IdOnly</t:BaseShape>'
        f'<t:AdditionalProperties>{_MESSAGE_PROPS}</t:AdditionalProperties></m:ItemShape>'
        f'<m:IndexedPageItemView MaxEntriesReturned="{min(limit,100)}" Offset="0" BasePoint="Beginning"/>'
        f'<m:ParentFolderIds>{_distinguished(folder or "inbox")}</m:ParentFolderIds>'
        f'<m:QueryString>{_esc(query)}</m:QueryString>'
        '</m:FindItem>'
    )
    body = call(client, cache_file, settings, inner, account_id)
    _check_response_messages(body)
    return [norm_message(m) for m in body.iter() if m.tag.endswith("}Message")]


def get_message(client, cache_file, settings, *, account_id, item_id, body_type="Text"):
    inner = (
        "<m:GetItem>"
        f'<m:ItemShape><t:BaseShape>Default</t:BaseShape><t:BodyType>{body_type}</t:BodyType>'
        f'<t:AdditionalProperties>{_MESSAGE_PROPS}</t:AdditionalProperties></m:ItemShape>'
        f'<m:ItemIds><t:ItemId Id="{_esc(item_id)}"/></m:ItemIds>'
        "</m:GetItem>"
    )
    body = call(client, cache_file, settings, inner, account_id)
    _check_response_messages(body)
    msgs = [m for m in body.iter() if m.tag.endswith("}Message")]
    if not msgs:
        raise OwaError(f"Item {item_id} not found")
    return norm_message(msgs[0])


# ---------------------------------------------------------------------------
# Mail: write
# ---------------------------------------------------------------------------
def send_message(client, cache_file, settings, *, account_id, to, subject, body, cc=None, bcc=None, html=False):
    inner = (
        '<m:CreateItem MessageDisposition="SendAndSaveCopy">'
        f"<m:Items>{_message_xml(subject, body, to, cc, bcc, html)}</m:Items>"
        "</m:CreateItem>"
    )
    resp = call(client, cache_file, settings, inner, account_id)
    _check_response_messages(resp)
    return {"status": "sent"}


def create_draft(client, cache_file, settings, *, account_id, to, subject, body, cc=None, bcc=None, html=False):
    inner = (
        '<m:CreateItem MessageDisposition="SaveOnly">'
        '<m:SavedItemFolderId><t:DistinguishedFolderId Id="drafts"/></m:SavedItemFolderId>'
        f"<m:Items>{_message_xml(subject, body, to, cc, bcc, html)}</m:Items>"
        "</m:CreateItem>"
    )
    resp = call(client, cache_file, settings, inner, account_id)
    _check_response_messages(resp)
    msgs = [m for m in resp.iter() if m.tag.endswith("}Message")]
    iid = _item_id(msgs[0]) if msgs else {}
    return {"status": "drafted", "id": iid.get("id")}


def reply_message(client, cache_file, settings, *, account_id, item_id, body, reply_all=False, html=False):
    tag = "ReplyAllToItem" if reply_all else "ReplyToItem"
    body_type = "HTML" if html else "Text"
    # ReplyToItem's ReferenceItemId requires the message's current ChangeKey;
    # fetch it first (it shifts whenever the item is modified).
    info = get_message(client, cache_file, settings, account_id=account_id, item_id=item_id)
    change_key = info.get("changeKey")
    ref = f'<t:ReferenceItemId Id="{_esc(item_id)}"' + (f' ChangeKey="{_esc(change_key)}"' if change_key else "") + "/>"
    inner = (
        '<m:CreateItem MessageDisposition="SendAndSaveCopy">'
        "<m:Items>"
        f"<t:{tag}>"
        f"{ref}"
        f'<t:NewBodyContent BodyType="{body_type}">{_esc(body)}</t:NewBodyContent>'
        f"</t:{tag}>"
        "</m:Items>"
        "</m:CreateItem>"
    )
    resp = call(client, cache_file, settings, inner, account_id)
    _check_response_messages(resp)
    return {"status": "sent"}


def update_message(client, cache_file, settings, *, account_id, item_id, is_read=None, categories=None):
    sets = ""
    if is_read is not None:
        sets += (
            "<t:SetItemField>"
            '<t:FieldURI FieldURI="message:IsRead"/>'
            f"<t:Message><t:IsRead>{'true' if is_read else 'false'}</t:IsRead></t:Message>"
            "</t:SetItemField>"
        )
    if categories is not None:
        cat_xml = "".join(f"<t:String>{_esc(c)}</t:String>" for c in categories)
        sets += (
            "<t:SetItemField>"
            '<t:FieldURI FieldURI="item:Categories"/>'
            f"<t:Item><t:Categories>{cat_xml}</t:Categories></t:Item>"
            "</t:SetItemField>"
        )
    if not sets:
        raise OwaError("nothing to update")
    inner = (
        '<m:UpdateItem MessageDisposition="SaveOnly" ConflictResolution="AlwaysOverwrite">'
        "<m:ItemChanges><t:ItemChange>"
        f'<t:ItemId Id="{_esc(item_id)}"/>'
        f"<t:Updates>{sets}</t:Updates>"
        "</t:ItemChange></m:ItemChanges>"
        "</m:UpdateItem>"
    )
    resp = call(client, cache_file, settings, inner, account_id)
    _check_response_messages(resp)
    return {"status": "updated", "id": item_id}


def delete_message(client, cache_file, settings, *, account_id, item_id, permanent=False):
    delete_type = "HardDelete" if permanent else "MoveToDeletedItems"
    inner = (
        f'<m:DeleteItem DeleteType="{delete_type}">'
        f'<m:ItemIds><t:ItemId Id="{_esc(item_id)}"/></m:ItemIds>'
        "</m:DeleteItem>"
    )
    resp = call(client, cache_file, settings, inner, account_id)
    _check_response_messages(resp)
    return {"status": "deleted", "mode": "permanent" if permanent else "soft", "email_id": item_id}


def delete_by_sender(client, cache_file, settings, *, account_id, sender, permanent=False, scan=200):
    # EWS AQS restriction by sender, then delete each match.
    msgs = search_messages(client, cache_file, settings, account_id=account_id, query=f"from:{sender}", folder="inbox", limit=scan)
    deleted = []
    for m in msgs:
        frm = (m.get("from") or {}).get("emailAddress", {}).get("address", "").lower()
        if frm == sender.lower():
            delete_message(client, cache_file, settings, account_id=account_id, item_id=m["id"], permanent=permanent)
            deleted.append(m["id"])
    return {"status": "deleted", "mode": "permanent" if permanent else "soft", "sender": sender,
            "deleted_count": len(deleted), "deleted_ids": deleted}


def get_attachment(client, cache_file, settings, *, account_id, attachment_id):
    inner = (
        "<m:GetAttachment><m:AttachmentIds>"
        f'<t:AttachmentId Id="{_esc(attachment_id)}"/>'
        "</m:AttachmentIds></m:GetAttachment>"
    )
    body = call(client, cache_file, settings, inner, account_id)
    _check_response_messages(body)
    fa = next((a for a in body.iter() if a.tag.endswith("}FileAttachment")), None)
    if fa is None:
        raise OwaError("attachment not found")
    return {
        "name": _text(fa, "t:Name"),
        "contentType": _text(fa, "t:ContentType"),
        "contentBytes": _text(fa, "t:Content"),  # base64
    }


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------
_EVENT_PROPS = (
    '<t:FieldURI FieldURI="item:Subject"/>'
    '<t:FieldURI FieldURI="calendar:Start"/>'
    '<t:FieldURI FieldURI="calendar:End"/>'
    '<t:FieldURI FieldURI="calendar:Location"/>'
    '<t:FieldURI FieldURI="calendar:Organizer"/>'
    '<t:FieldURI FieldURI="calendar:IsAllDayEvent"/>'
)


def list_events(client, cache_file, settings, *, account_id, start_utc, end_utc, limit=100):
    inner = (
        '<m:FindItem Traversal="Shallow">'
        '<m:ItemShape><t:BaseShape>IdOnly</t:BaseShape>'
        f'<t:AdditionalProperties>{_EVENT_PROPS}</t:AdditionalProperties></m:ItemShape>'
        f'<m:CalendarView MaxEntriesReturned="{min(limit,1000)}" StartDate="{_esc(start_utc)}" EndDate="{_esc(end_utc)}"/>'
        '<m:ParentFolderIds><t:DistinguishedFolderId Id="calendar"/></m:ParentFolderIds>'
        '</m:FindItem>'
    )
    body = call(client, cache_file, settings, inner, account_id)
    _check_response_messages(body)
    return [norm_event(e) for e in body.iter() if e.tag.endswith("}CalendarItem")]


def list_calendars(client, cache_file, settings, *, account_id):
    inner = (
        '<m:FindFolder Traversal="Deep">'
        '<m:FolderShape><t:BaseShape>Default</t:BaseShape></m:FolderShape>'
        '<m:Restriction><t:IsEqualTo>'
        '<t:FieldURI FieldURI="folder:FolderClass"/>'
        '<t:FieldURIOrConstant><t:Constant Value="IPF.Appointment"/></t:FieldURIOrConstant>'
        '</t:IsEqualTo></m:Restriction>'
        '<m:ParentFolderIds><t:DistinguishedFolderId Id="msgfolderroot"/></m:ParentFolderIds>'
        '</m:FindFolder>'
    )
    body = call(client, cache_file, settings, inner, account_id)
    _check_response_messages(body)
    out = []
    for f in body.iter():
        if f.tag.endswith("}CalendarFolder") or f.tag.endswith("}Folder"):
            fid = f.find("t:FolderId", _NS)
            name = _text(f, "t:DisplayName")
            if name:
                out.append({"id": fid.attrib.get("Id") if fid is not None else None, "name": name})
    return out


def get_event(client, cache_file, settings, *, account_id, event_id):
    inner = (
        "<m:GetItem>"
        '<m:ItemShape><t:BaseShape>Default</t:BaseShape><t:BodyType>Text</t:BodyType>'
        f'<t:AdditionalProperties>{_EVENT_PROPS}</t:AdditionalProperties></m:ItemShape>'
        f'<m:ItemIds><t:ItemId Id="{_esc(event_id)}"/></m:ItemIds>'
        "</m:GetItem>"
    )
    body = call(client, cache_file, settings, inner, account_id)
    _check_response_messages(body)
    evs = [e for e in body.iter() if e.tag.endswith("}CalendarItem")]
    if not evs:
        raise OwaError(f"event {event_id} not found")
    return norm_event(evs[0])


def create_event(client, cache_file, settings, *, account_id, subject, start, end, timezone,
                 location=None, body=None, attendees=None, is_all_day=False):
    parts = [f"<t:Subject>{_esc(subject)}</t:Subject>"]
    if body:
        parts.append(f'<t:Body BodyType="Text">{_esc(body)}</t:Body>')
    parts.append(f"<t:Start>{_esc(start)}</t:Start>")
    parts.append(f"<t:End>{_esc(end)}</t:End>")
    if is_all_day:
        parts.append("<t:IsAllDayEvent>true</t:IsAllDayEvent>")
    if location:
        parts.append(f"<t:Location>{_esc(location)}</t:Location>")
    if attendees:
        boxes = "".join(
            f"<t:Attendee><t:Mailbox><t:EmailAddress>{_esc(a)}</t:EmailAddress></t:Mailbox></t:Attendee>"
            for a in attendees
        )
        parts.append(f"<t:RequiredAttendees>{boxes}</t:RequiredAttendees>")
    # Start/End are passed as UTC ('...Z') by the adapter, so we declare the UTC
    # zone explicitly. StartTimeZone/EndTimeZone are the Exchange2013 elements;
    # the older MeetingTimeZone is rejected by this RequestServerVersion. These
    # are the last elements in the CalendarItem schema, so they go at the end.
    parts.append('<t:StartTimeZone Id="UTC"/><t:EndTimeZone Id="UTC"/>')
    inner = (
        '<m:CreateItem SendMeetingInvitations="SendToAllAndSaveCopy">'
        f"<m:Items><t:CalendarItem>{''.join(parts)}</t:CalendarItem></m:Items>"
        "</m:CreateItem>"
    )
    resp = call(client, cache_file, settings, inner, account_id)
    _check_response_messages(resp)
    evs = [e for e in resp.iter() if e.tag.endswith("}CalendarItem")]
    iid = _item_id(evs[0]) if evs else {}
    return {"status": "created", "id": iid.get("id")}


def update_event(client, cache_file, settings, *, account_id, event_id, subject=None, start=None,
                 end=None, location=None, body=None, timezone=None):
    sets = ""

    def field(uri, holder_tag, inner_xml):
        return f'<t:SetItemField><t:FieldURI FieldURI="{uri}"/><t:CalendarItem>{inner_xml}</t:CalendarItem></t:SetItemField>'

    if subject is not None:
        sets += field("item:Subject", "CalendarItem", f"<t:Subject>{_esc(subject)}</t:Subject>")
    if start is not None:
        sets += field("calendar:Start", "CalendarItem", f"<t:Start>{_esc(start)}</t:Start>")
    if end is not None:
        sets += field("calendar:End", "CalendarItem", f"<t:End>{_esc(end)}</t:End>")
    if location is not None:
        sets += field("calendar:Location", "CalendarItem", f"<t:Location>{_esc(location)}</t:Location>")
    if body is not None:
        sets += field("item:Body", "CalendarItem", f'<t:Body BodyType="Text">{_esc(body)}</t:Body>')
    if not sets:
        raise OwaError("nothing to update")
    inner = (
        '<m:UpdateItem ConflictResolution="AlwaysOverwrite"'
        ' MessageDisposition="SaveOnly" SendMeetingInvitationsOrCancellations="SendToAllAndSaveCopy">'
        "<m:ItemChanges><t:ItemChange>"
        f'<t:ItemId Id="{_esc(event_id)}"/>'
        f"<t:Updates>{sets}</t:Updates>"
        "</t:ItemChange></m:ItemChanges>"
        "</m:UpdateItem>"
    )
    resp = call(client, cache_file, settings, inner, account_id)
    _check_response_messages(resp)
    return {"status": "updated", "id": event_id}


def delete_event(client, cache_file, settings, *, account_id, event_id, send_cancellation=True):
    mode = "SendToAllAndSaveCopy" if send_cancellation else "SendToNone"
    inner = (
        f'<m:DeleteItem DeleteType="MoveToDeletedItems" SendMeetingCancellations="{mode}">'
        f'<m:ItemIds><t:ItemId Id="{_esc(event_id)}"/></m:ItemIds>'
        "</m:DeleteItem>"
    )
    resp = call(client, cache_file, settings, inner, account_id)
    _check_response_messages(resp)
    return {"status": "deleted", "event_id": event_id}


def respond_event(client, cache_file, settings, *, account_id, event_id, response="accept", message=None):
    tag = {"accept": "AcceptItem", "decline": "DeclineItem", "tentativelyAccept": "TentativelyAcceptItem"}[response]
    body_xml = f'<t:Body BodyType="Text">{_esc(message)}</t:Body>' if message else ""
    inner = (
        '<m:CreateItem MessageDisposition="SendAndSaveCopy">'
        "<m:Items>"
        f"<t:{tag}>{body_xml}<t:ReferenceItemId Id=\"{_esc(event_id)}\"/></t:{tag}>"
        "</m:Items>"
        "</m:CreateItem>"
    )
    resp = call(client, cache_file, settings, inner, account_id)
    _check_response_messages(resp)
    return {"status": response}


# ---------------------------------------------------------------------------
# Inbox rules (block / unblock sender)
# ---------------------------------------------------------------------------
BLOCK_RULE_PREFIX = "Block "


def list_block_rules(client, cache_file, settings, *, account_id):
    body = call(client, cache_file, settings, "<m:GetInboxRules/>", account_id)
    out = []
    for rule in body.iter():
        if rule.tag.endswith("}Rule"):
            name = _text(rule, "t:DisplayName") or ""
            if name.startswith(BLOCK_RULE_PREFIX):
                conds = rule.find("t:Conditions", _NS)
                addrs = []
                if conds is not None:
                    fa = conds.find("t:FromAddresses", _NS)
                    if fa is not None:
                        addrs = [_text(a, "t:EmailAddress") for a in fa.findall("t:Address", _NS)]
                out.append({"id": _text(rule, "t:RuleId"), "displayName": name, "blockedSenders": addrs})
    return out


def block_sender(client, cache_file, settings, *, account_id, sender):
    inner = (
        "<m:UpdateInboxRules><m:Operations><t:CreateRuleOperation><t:Rule>"
        f"<t:DisplayName>{_esc(BLOCK_RULE_PREFIX + sender)}</t:DisplayName>"
        "<t:Priority>1</t:Priority><t:IsEnabled>true</t:IsEnabled>"
        "<t:Conditions><t:FromAddresses>"
        f"<t:Address><t:EmailAddress>{_esc(sender)}</t:EmailAddress></t:Address>"
        "</t:FromAddresses></t:Conditions>"
        '<t:Actions><t:MoveToFolder><t:DistinguishedFolderId Id="junkemail"/></t:MoveToFolder>'
        "<t:StopProcessingRules>true</t:StopProcessingRules></t:Actions>"
        "</t:Rule></t:CreateRuleOperation></m:Operations></m:UpdateInboxRules>"
    )
    body = call(client, cache_file, settings, inner, account_id)
    # UpdateInboxRules returns a single response code, not per-message items.
    code = next((e.text for e in body.iter() if e.tag.endswith("}ResponseCode")), None)
    if code and code != "NoError":
        raise OwaError(f"block failed: {code}")
    return {"status": "blocked", "sender": sender}


def unblock_sender(client, cache_file, settings, *, account_id, sender):
    rules = list_block_rules(client, cache_file, settings, account_id=account_id)
    targets = [r for r in rules if sender.lower() in [s.lower() for s in (r.get("blockedSenders") or []) if s]]
    if not targets:
        return {"status": "not_found", "sender": sender}
    deleted = []
    for r in targets:
        inner = (
            "<m:UpdateInboxRules><m:Operations><t:DeleteRuleOperation>"
            f"<t:RuleId>{_esc(r['id'])}</t:RuleId>"
            "</t:DeleteRuleOperation></m:Operations></m:UpdateInboxRules>"
        )
        body = call(client, cache_file, settings, inner, account_id)
        code = next((e.text for e in body.iter() if e.tag.endswith("}ResponseCode")), None)
        if code and code != "NoError":
            raise OwaError(f"unblock failed: {code}")
        deleted.append(r["id"])
    return {"status": "unblocked", "sender": sender, "deleted_rule_ids": deleted}
