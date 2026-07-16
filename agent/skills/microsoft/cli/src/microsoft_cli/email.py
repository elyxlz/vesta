"""Email commands for Microsoft CLI."""

import base64
import html
import pathlib as pl
from datetime import UTC, datetime
from typing import Any

import httpx

from . import auth, folders, graph
from .config import Config

EMAIL_SAVE_SUBDIR = "emails"
LARGE_ATTACHMENT_THRESHOLD = 3 * 1024 * 1024
LONG_EMAIL_WARNING_THRESHOLD = 5000
EMAIL_SNAPSHOT_FIELDS = [
    "id",
    "subject",
    "from",
    "toRecipients",
    "ccRecipients",
    "receivedDateTime",
    "hasAttachments",
    "conversationId",
    "isRead",
    "bodyPreview",
]
EMAIL_SNAPSHOT_SELECT = ",".join(EMAIL_SNAPSHOT_FIELDS)


def _file_attachment(name: str, content_bytes: bytes) -> dict[str, str]:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": name,
        "contentBytes": base64.b64encode(content_bytes).decode("utf-8"),
    }


def _read_attachment(file_path: str) -> tuple[bytes, str, int]:
    """Read an attachment file, returning (content_bytes, name, size_bytes)."""
    path = pl.Path(file_path).expanduser().resolve()
    content_bytes = path.read_bytes()
    return content_bytes, path.name, len(content_bytes)


def _attach_files(config: Config, client: httpx.Client, message_id: str, attachments: list[str] | None, account_id: str) -> None:
    """Attach files to an existing draft, small ones inline and large ones via upload session."""
    if not attachments:
        return
    for file_path in attachments:
        content_bytes, att_name, att_size = _read_attachment(file_path)
        if att_size < LARGE_ATTACHMENT_THRESHOLD:
            graph.request_cfg(
                config, client, "POST", f"/me/messages/{message_id}/attachments", account_id, json=_file_attachment(att_name, content_bytes)
            )
        else:
            graph.upload_mail_attachment_cfg(config, client, message_id, att_name, content_bytes, account_id)


def _remove_attachment_bytes(result: dict[str, Any]) -> None:
    if result.get("attachments"):
        for attachment in result["attachments"]:
            if "contentBytes" in attachment:
                del attachment["contentBytes"]


def _sanitize_filename(value: str) -> str:
    sanitized = "".join(char if char.isalnum() else "_" for char in value or "")
    sanitized = sanitized.strip("_")
    return sanitized or "email"


def _prepare_email_output_path(
    config: Config,
    email_id: str,
    subject: str | None,
    override_path: str | None,
) -> pl.Path:
    if override_path:
        path = pl.Path(override_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    base_dir = config.cache_file.parent / EMAIL_SAVE_SUBDIR
    base_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    subject_fragment = _sanitize_filename(subject or "")
    id_fragment = _sanitize_filename(email_id)[:32]
    filename = f"{timestamp}_{subject_fragment[:40]}_{id_fragment}.txt".strip("_")

    return base_dir / filename


def _extract_addresses(recipients: list[dict[str, Any]]) -> str:
    return ", ".join(
        (r["emailAddress"] if "emailAddress" in r else {})["address"] if "address" in (r["emailAddress"] if "emailAddress" in r else {}) else ""
        for r in recipients
    )


def _scrub_email_snapshot(record: dict[str, Any]) -> None:
    record.pop("body", None)
    if "bodyPreview" in record:
        record.setdefault("preview", record.pop("bodyPreview"))


def _resolve_mail_endpoint(config: Config, folder: str | None) -> str:
    if folder:
        folder_path = config.folders[folder.casefold()] if folder.casefold() in config.folders else folder
        return f"/me/mailFolders/{folder_path}/messages"
    return "/me/messages"


def _search_mailbox_messages(
    config: Config,
    client: httpx.Client,
    account_id: str,
    endpoint: str,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    params = {
        "$search": f'"{query}"',
        "$top": min(limit, 100),
        "$select": EMAIL_SNAPSHOT_SELECT,
    }
    emails = list(graph.paginate_cfg(config, client, endpoint, account_id, params=params, limit=limit))
    for email in emails:
        _scrub_email_snapshot(email)
        graph.localize_datetime_fields(email)
    return emails


def list_emails(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    folder: str = "inbox",
    limit: int = 10,
) -> list[dict[str, Any]]:
    account_id = auth.get_account_id_by_email(account_email, config.cache_file)

    folder_path = config.folders[folder.casefold()] if folder.casefold() in config.folders else folder

    params = {
        "$top": min(limit, 100),
        "$select": EMAIL_SNAPSHOT_SELECT,
        "$orderby": "receivedDateTime desc",
    }

    emails = list(graph.paginate_cfg(config, client, f"/me/mailFolders/{folder_path}/messages", account_id, params=params, limit=limit))

    for email in emails:
        _scrub_email_snapshot(email)
        graph.localize_datetime_fields(email)

    return emails


def get_email(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    email_id: str,
    include_attachments: bool = True,
    save_to_file: str | None = None,
) -> dict[str, Any]:
    account_id = auth.get_account_id_by_email(account_email, config.cache_file)
    params: dict[str, Any] = {
        "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,hasAttachments,conversationId,isRead,body,bodyPreview",
    }
    if include_attachments:
        params["$expand"] = "attachments($select=id,name,size,contentType)"

    result = graph.request_cfg(config, client, "GET", f"/me/messages/{email_id}", account_id, params=params)
    if not result:
        raise ValueError(f"Email with ID {email_id} not found")

    graph.localize_datetime_fields(result)
    return finalize_email_body(config, email_id, result, save_to_file)


def finalize_email_body(config: Config, email_id: str, result: dict[str, Any], save_to_file: str | None) -> dict[str, Any]:
    """Persist an email body to disk and replace it with a pointer in the returned
    dict. Shared by the Graph path and the OWA/EWS fallback so `email get` returns
    an identical shape regardless of which backend fetched the message. `result`
    must be a Graph-shaped message dict carrying a `body` of {contentType, content}.
    """
    body_obj = result["body"] if "body" in result else None
    full_body_content = (body_obj["content"] if body_obj and "content" in body_obj else "") or ""
    _remove_attachment_bytes(result)

    save_path = _prepare_email_output_path(config, email_id, result["subject"] if "subject" in result else None, save_to_file)

    from_obj = result["from"] if "from" in result else {}
    from_email_obj = from_obj["emailAddress"] if "emailAddress" in from_obj else {}
    from_addr = from_email_obj["address"] if "address" in from_email_obj else "unknown"

    to_addrs = _extract_addresses(result["toRecipients"] if "toRecipients" in result else [])

    content_lines = [
        f"From: {from_addr}",
        f"Subject: {result['subject'] if 'subject' in result else 'No subject'}",
        f"Date: {result['receivedDateTime'] if 'receivedDateTime' in result else 'unknown'}",
        f"To: {to_addrs}",
    ]

    cc_recipients = result["ccRecipients"] if "ccRecipients" in result else []
    if cc_recipients:
        content_lines.append(f"Cc: {_extract_addresses(cc_recipients)}")

    content_lines.extend(["", "=" * 80, "", full_body_content])

    save_path.write_text("\n".join(content_lines), encoding="utf-8")
    saved_size = save_path.stat().st_size

    result["body"] = {
        "saved_to": str(save_path),
        "length": len(full_body_content),
        "size_bytes": saved_size,
        "_note": "body saved to disk to keep agent context small; read the file at saved_to",
    }
    result["body_saved_to"] = str(save_path)
    result["body_saved_size"] = saved_size
    result["body_length"] = len(full_body_content)

    if "bodyPreview" in result:
        result["preview"] = result.pop("bodyPreview")

    if result["body_length"] > LONG_EMAIL_WARNING_THRESHOLD:
        warning = (
            f"Email body is {result['body_length']} characters; inspect {result['body_saved_to']} "
            "and grep/crop/filter before pasting snippets to avoid overflowing context."
        )
        result.setdefault("warnings", []).append(warning)

    return result


def create_email_draft(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    body: str,
    subject: str | None = None,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[str] | None = None,
    reply_to_id: str | None = None,
    forward_id: str | None = None,
) -> dict[str, Any]:
    if reply_to_id and forward_id:
        raise ValueError("Specify at most one of --reply-to or --forward")

    account_id = auth.get_account_id_by_email(account_email, config.cache_file)

    if reply_to_id or forward_id:
        source_id = reply_to_id or forward_id
        create_endpoint = "createReply" if reply_to_id else "createForward"
        draft = graph.request_cfg(config, client, "POST", f"/me/messages/{source_id}/{create_endpoint}", account_id)
        if not draft or "id" not in draft:
            raise ValueError("Failed to create reply/forward draft")
        draft_id = draft["id"]

        updates: dict[str, Any] = {"body": {"contentType": "Text", "content": body}}
        if subject:
            updates["subject"] = subject
        if to:
            updates["toRecipients"] = [{"emailAddress": {"address": addr}} for addr in to]
        if cc:
            updates["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]
        if bcc:
            updates["bccRecipients"] = [{"emailAddress": {"address": addr}} for addr in bcc]
        graph.request_cfg(config, client, "PATCH", f"/me/messages/{draft_id}", account_id, json=updates)

        _attach_files(config, client, draft_id, attachments, account_id)
        return {"status": "drafted", "id": draft_id, "source_id": source_id}

    if not subject:
        raise ValueError("--subject is required for a new draft")
    if not to and not cc and not bcc:
        raise ValueError("At least one recipient is required (--to, --cc, or --bcc)")

    message = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": addr}} for addr in to] if to else [],
    }

    if cc:
        message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]
    if bcc:
        message["bccRecipients"] = [{"emailAddress": {"address": addr}} for addr in bcc]

    small_attachments = []
    large_attachments = []

    if attachments:
        for file_path in attachments:
            content_bytes, att_name, att_size = _read_attachment(file_path)

            if att_size < LARGE_ATTACHMENT_THRESHOLD:
                small_attachments.append(_file_attachment(att_name, content_bytes))
            else:
                large_attachments.append(
                    {
                        "name": att_name,
                        "content_bytes": content_bytes,
                        "content_type": "application/octet-stream",
                    }
                )

    if small_attachments:
        message["attachments"] = small_attachments

    result = graph.request_cfg(config, client, "POST", "/me/messages", account_id, json=message)
    if not result:
        raise ValueError("Failed to create email draft")

    message_id = result["id"]

    for att in large_attachments:
        graph.upload_mail_attachment_cfg(
            config,
            client,
            message_id,
            att["name"],
            att["content_bytes"],
            account_id,
            att["content_type"] if "content_type" in att else "application/octet-stream",
        )

    return result


def send_email(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    to: list[str] | None = None,
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[str] | None = None,
    html: bool = False,
) -> dict[str, str]:
    if not to and not cc and not bcc:
        raise ValueError("At least one recipient is required (--to, --cc, or --bcc)")

    account_id = auth.get_account_id_by_email(account_email, config.cache_file)

    message = {
        "subject": subject,
        "body": {"contentType": "HTML" if html else "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": addr}} for addr in to] if to else [],
    }

    if cc:
        message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]
    if bcc:
        message["bccRecipients"] = [{"emailAddress": {"address": addr}} for addr in bcc]

    has_large_attachments = False
    processed_attachments = []

    if attachments:
        for file_path in attachments:
            content_bytes, att_name, att_size = _read_attachment(file_path)

            processed_attachments.append(
                {
                    "name": att_name,
                    "content_bytes": content_bytes,
                    "content_type": "application/octet-stream",
                    "size": att_size,
                }
            )

            if att_size >= LARGE_ATTACHMENT_THRESHOLD:
                has_large_attachments = True

    if not has_large_attachments and processed_attachments:
        message["attachments"] = [_file_attachment(att["name"], att["content_bytes"]) for att in processed_attachments]
        graph.request_cfg(config, client, "POST", "/me/sendMail", account_id, json={"message": message})
        return {"status": "sent"}
    if has_large_attachments:
        result = graph.request_cfg(config, client, "POST", "/me/messages", account_id, json=message)
        if not result:
            raise ValueError("Failed to create email draft")

        message_id = result["id"]

        for att in processed_attachments:
            if att["size"] >= LARGE_ATTACHMENT_THRESHOLD:
                graph.upload_mail_attachment_cfg(
                    config,
                    client,
                    message_id,
                    att["name"],
                    att["content_bytes"],
                    account_id,
                    att["content_type"] if "content_type" in att else "application/octet-stream",
                )
            else:
                small_att = _file_attachment(att["name"], att["content_bytes"])
                graph.request_cfg(config, client, "POST", f"/me/messages/{message_id}/attachments", account_id, json=small_att)

        graph.request_cfg(config, client, "POST", f"/me/messages/{message_id}/send", account_id)
        return {"status": "sent"}
    graph.request_cfg(config, client, "POST", "/me/sendMail", account_id, json={"message": message})
    return {"status": "sent"}


def reply_to_email(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    email_id: str,
    body: str,
    attachments: list[str] | None = None,
    reply_all: bool = False,
    html: bool = False,
) -> dict[str, str]:
    account_id = auth.get_account_id_by_email(account_email, config.cache_file)
    create_endpoint = "createReplyAll" if reply_all else "createReply"
    reply_endpoint = "replyAll" if reply_all else "reply"

    if attachments:
        draft = graph.request_cfg(config, client, "POST", f"/me/messages/{email_id}/{create_endpoint}", account_id)
        if not draft or "id" not in draft:
            raise ValueError("Failed to create reply draft")

        draft_id = draft["id"]

        graph.request_cfg(
            config,
            client,
            "PATCH",
            f"/me/messages/{draft_id}",
            account_id,
            json={"body": {"contentType": "HTML" if html else "Text", "content": body}},
        )

        _attach_files(config, client, draft_id, attachments, account_id)

        graph.request_cfg(config, client, "POST", f"/me/messages/{draft_id}/send", account_id)
        return {"status": "sent"}
    endpoint = f"/me/messages/{email_id}/{reply_endpoint}"
    payload = {"message": {"body": {"contentType": "HTML" if html else "Text", "content": body}}}
    graph.request_cfg(config, client, "POST", endpoint, account_id, json=payload)
    return {"status": "sent"}


def _reply_body_to_html(raw: str) -> str:
    """Render a plain-text reply body as HTML so it can sit above the quoted history:
    `- ` lines become bullets, blank lines become spacing, everything else a div. Escaped
    so the body cannot inject markup."""
    parts: list[str] = []
    in_ul = False
    for line in raw.rstrip("\n").split("\n"):
        if line.startswith("- "):
            if not in_ul:
                parts.append("<ul>")
                in_ul = True
            parts.append("<li>" + html.escape(line[2:]) + "</li>")
        else:
            if in_ul:
                parts.append("</ul>")
                in_ul = False
            parts.append("<br>" if line.strip() == "" else "<div>" + html.escape(line) + "</div>")
    if in_ul:
        parts.append("</ul>")
    return "".join(parts)


def reply_draft(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    email_id: str,
    body: str,
    attachments: list[str] | None = None,
    reply_all: bool = False,
    replace_draft: str | None = None,
) -> dict[str, Any]:
    """Leave an UNSENT threaded reply(-all) draft for the user to review and send.

    `email reply` always sends and `email draft --reply-to` overwrites the quoted history;
    this fills the gap. createReply/createReplyAll pre-fills recipients + the quoted thread,
    the new body is placed above that preserved quote, files attach, and we STOP before /send.
    `--replace-draft` deletes a prior draft first so repeated edits leave exactly one draft."""
    account_id = auth.get_account_id_by_email(account_email, config.cache_file)

    warnings: list[str] = []
    if replace_draft:
        try:
            graph.request_cfg(config, client, "DELETE", f"/me/messages/{replace_draft}", account_id)
        except httpx.HTTPStatusError as exc:
            warnings.append(f"could not delete old draft {replace_draft}: {exc}")

    create_endpoint = "createReplyAll" if reply_all else "createReply"
    draft = graph.request_cfg(config, client, "POST", f"/me/messages/{email_id}/{create_endpoint}", account_id)
    if not draft or "id" not in draft:
        raise ValueError("Failed to create reply draft")
    draft_id = draft["id"]

    existing = graph.request_cfg(
        config, client, "GET", f"/me/messages/{draft_id}", account_id, params={"$select": "body,toRecipients,ccRecipients"}
    )
    if not existing or "body" not in existing:
        raise ValueError("Failed to read the created reply draft")
    quoted = existing["body"]["content"]
    to = _extract_addresses(existing["toRecipients"] if "toRecipients" in existing else [])
    cc = _extract_addresses(existing["ccRecipients"] if "ccRecipients" in existing else [])

    graph.request_cfg(
        config,
        client,
        "PATCH",
        f"/me/messages/{draft_id}",
        account_id,
        json={"body": {"contentType": "HTML", "content": _reply_body_to_html(body) + "<br><br>" + quoted}},
    )

    _attach_files(config, client, draft_id, attachments, account_id)

    check = graph.request_cfg(
        config,
        client,
        "GET",
        f"/me/messages/{draft_id}",
        account_id,
        params={"$select": "subject,isDraft", "$expand": "attachments($select=name,size)"},
    )
    result: dict[str, Any] = {
        "status": "drafted",
        "id": draft_id,
        "subject": check["subject"] if check and "subject" in check else None,
        "isDraft": check["isDraft"] if check and "isDraft" in check else None,
        "to": to,
        "cc": cc,
        "attachments": [a["name"] for a in (check["attachments"] if check and "attachments" in check else [])],
    }
    if warnings:
        result["warnings"] = warnings
    return result


def forward_email(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    email_id: str,
    to: list[str],
    body: str = "",
    cc: list[str] | None = None,
    attachments: list[str] | None = None,
    html: bool = False,
) -> dict[str, str]:
    if not to:
        raise ValueError("--to is required to forward")

    account_id = auth.get_account_id_by_email(account_email, config.cache_file)
    to_recipients = [{"emailAddress": {"address": addr}} for addr in to]

    # cc / html / attachments need the draft path (the one-shot forward action only
    # takes a plain-text comment + toRecipients); the plain case keeps the quoted original.
    if attachments or cc or html:
        draft = graph.request_cfg(config, client, "POST", f"/me/messages/{email_id}/createForward", account_id)
        if not draft or "id" not in draft:
            raise ValueError("Failed to create forward draft")
        draft_id = draft["id"]

        updates: dict[str, Any] = {
            "body": {"contentType": "HTML" if html else "Text", "content": body},
            "toRecipients": to_recipients,
        }
        if cc:
            updates["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]
        graph.request_cfg(config, client, "PATCH", f"/me/messages/{draft_id}", account_id, json=updates)

        _attach_files(config, client, draft_id, attachments, account_id)
        graph.request_cfg(config, client, "POST", f"/me/messages/{draft_id}/send", account_id)
        return {"status": "sent"}

    graph.request_cfg(
        config, client, "POST", f"/me/messages/{email_id}/forward", account_id, json={"comment": body, "toRecipients": to_recipients}
    )
    return {"status": "sent"}


def move_email(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    email_id: str,
    to_folder: str,
) -> dict[str, Any]:
    account_id = auth.get_account_id_by_email(account_email, config.cache_file)
    destination = folders.resolve_folder_id_cfg(config, client, account_id, to_folder)
    result = graph.request_cfg(config, client, "POST", f"/me/messages/{email_id}/move", account_id, json={"destinationId": destination})
    return {
        "status": "moved",
        "email_id": email_id,
        "to_folder": to_folder,
        "new_id": result["id"] if result and "id" in result else None,
    }


def archive_email(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    email_id: str,
) -> dict[str, Any]:
    return move_email(config, client, account_email=account_email, email_id=email_id, to_folder="archive")


def list_attachments(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    email_id: str,
) -> list[dict[str, Any]]:
    account_id = auth.get_account_id_by_email(account_email, config.cache_file)
    result = graph.request_cfg(
        config, client, "GET", f"/me/messages/{email_id}/attachments", account_id, params={"$select": "id,name,size,contentType"}
    )
    return result["value"] if result and "value" in result else []


def download_attachments(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    email_id: str,
    out_dir: str,
) -> dict[str, Any]:
    account_id = auth.get_account_id_by_email(account_email, config.cache_file)
    result = graph.request_cfg(config, client, "GET", f"/me/messages/{email_id}/attachments", account_id)
    attachments = result["value"] if result and "value" in result else []

    out = pl.Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    saved: list[dict[str, Any]] = []
    used: set[str] = set()
    for att in attachments:
        # item/reference attachments carry no inline bytes; only file attachments are downloadable.
        if "contentBytes" not in att:
            continue
        raw_name = att["name"] if "name" in att else "attachment"
        stem = pl.Path(raw_name).stem or "attachment"
        suffix = pl.Path(raw_name).suffix
        name = f"{stem}{suffix}"
        counter = 1
        while name in used:
            name = f"{stem}_{counter}{suffix}"
            counter += 1
        used.add(name)

        path = out / name
        path.write_bytes(base64.b64decode(att["contentBytes"]))
        saved.append({"name": raw_name, "saved_to": str(path), "size": att["size"] if "size" in att else 0})

    return {"email_id": email_id, "count": len(saved), "saved": saved}


def get_attachment(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    email_id: str,
    attachment_id: str,
    save_path: str,
) -> dict[str, Any]:
    account_id = auth.get_account_id_by_email(account_email, config.cache_file)
    result = graph.request_cfg(config, client, "GET", f"/me/messages/{email_id}/attachments/{attachment_id}", account_id)

    if not result:
        raise ValueError("Attachment not found")

    if "contentBytes" not in result:
        raise ValueError("Attachment content not available")

    path = pl.Path(save_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    content_bytes = base64.b64decode(result["contentBytes"])
    path.write_bytes(content_bytes)

    return {
        "name": result["name"] if "name" in result else "unknown",
        "content_type": result["contentType"] if "contentType" in result else "application/octet-stream",
        "size": result["size"] if "size" in result else 0,
        "saved_to": str(path),
    }


def search_emails(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    query: str,
    limit: int = 10,
    folder: str | None = None,
) -> list[dict[str, Any]]:
    account_id = auth.get_account_id_by_email(account_email, config.cache_file)
    endpoint = _resolve_mail_endpoint(config, folder)
    return _search_mailbox_messages(config, client, account_id, endpoint, query, limit)


def _delete_message(
    config: Config,
    client: httpx.Client,
    account_id: str,
    email_id: str,
    permanent: bool,
) -> None:
    if permanent:
        graph.request_cfg(config, client, "DELETE", f"/me/messages/{email_id}", account_id)
    else:
        graph.request_cfg(config, client, "POST", f"/me/messages/{email_id}/move", account_id, json={"destinationId": "deleteditems"})


def delete_email(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    email_id: str | None = None,
    sender: str | None = None,
    permanent: bool = False,
) -> dict[str, Any]:
    if (email_id is None) == (sender is None):
        raise ValueError("Specify exactly one of --id or --sender")

    account_id = auth.get_account_id_by_email(account_email, config.cache_file)
    mode = "permanent" if permanent else "soft"

    if email_id is not None:
        _delete_message(config, client, account_id, email_id, permanent)
        return {"status": "deleted", "mode": mode, "email_id": email_id}

    params = {
        "$filter": f"from/emailAddress/address eq '{sender}'",
        "$top": 100,
        "$select": "id",
    }
    messages = list(graph.paginate_cfg(config, client, "/me/messages", account_id, params=params))

    deleted_ids = []
    for message in messages:
        _delete_message(config, client, account_id, message["id"], permanent)
        deleted_ids.append(message["id"])

    return {"status": "deleted", "mode": mode, "sender": sender, "deleted_count": len(deleted_ids), "deleted_ids": deleted_ids}


def update_email(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    email_id: str,
    is_read: bool | None = None,
    categories: list[str] | None = None,
    flagged: bool | None = None,
) -> dict[str, Any]:
    account_id = auth.get_account_id_by_email(account_email, config.cache_file)

    updates: dict[str, Any] = {}
    if is_read is not None:
        updates["isRead"] = is_read
    if categories is not None:
        updates["categories"] = categories
    if flagged is not None:
        updates["flag"] = {"flagStatus": "flagged" if flagged else "notFlagged"}

    if not updates:
        raise ValueError("Must specify at least one field to update (is_read, categories, or flagged)")

    result = graph.request_cfg(config, client, "PATCH", f"/me/messages/{email_id}", account_id, json=updates)
    return result or {"status": "updated", "email_id": email_id}
