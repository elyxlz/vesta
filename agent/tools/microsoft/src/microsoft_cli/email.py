"""Email commands for Microsoft CLI."""

import base64
import pathlib as pl
from datetime import datetime, UTC
from typing import Any

import httpx

from . import graph, auth
from .config import Config
from .settings import MicrosoftSettings

EMAIL_SAVE_SUBDIR = "emails"
LONG_EMAIL_WARNING_THRESHOLD = 5000
LARGE_ATTACHMENT_THRESHOLD = LARGE_ATTACHMENT_THRESHOLD
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


def _get_settings() -> MicrosoftSettings:
    return MicrosoftSettings()


def _remove_attachment_bytes(result: dict[str, Any]) -> None:
    if "attachments" in result and result["attachments"]:
        for attachment in result["attachments"]:
            if "contentBytes" in attachment:
                del attachment["contentBytes"]


def _extract_addresses(recipients: list[dict]) -> str:
    addrs = []
    for r in recipients:
        email_obj = r["emailAddress"] if "emailAddress" in r else {}
        addrs.append(email_obj["address"] if "address" in email_obj else "")
    return ", ".join(addrs)


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


def _scrub_email_snapshot(record: dict[str, Any]) -> None:
    if "body" in record:
        del record["body"]
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
    settings = _get_settings()
    params = {
        "$search": f'"{query}"',
        "$top": min(limit, 100),
        "$select": EMAIL_SNAPSHOT_SELECT,
    }
    emails = list(
        graph.request_paginated(
            client,
            config.cache_file,
            config.scopes,
            settings,
            config.base_url,
            endpoint,
            account_id,
            params=params,
            limit=limit,
        )
    )
    for email in emails:
        _scrub_email_snapshot(email)
    return emails


def list_emails(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    folder: str = "inbox",
    limit: int = 10,
) -> list[dict[str, Any]]:
    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)

    folder_path = config.folders[folder.casefold()] if folder.casefold() in config.folders else folder

    params = {
        "$top": min(limit, 100),
        "$select": EMAIL_SNAPSHOT_SELECT,
        "$orderby": "receivedDateTime desc",
    }

    emails = list(
        graph.request_paginated(
            client,
            config.cache_file,
            config.scopes,
            settings,
            config.base_url,
            f"/me/mailFolders/{folder_path}/messages",
            account_id,
            params=params,
            limit=limit,
        )
    )

    for email in emails:
        _scrub_email_snapshot(email)

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
    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)
    params: dict[str, Any] = {
        "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,hasAttachments,conversationId,isRead,body,bodyPreview",
    }
    if include_attachments:
        params["$expand"] = "attachments($select=id,name,size,contentType)"

    result = graph.request(
        client,
        config.cache_file,
        config.scopes,
        settings,
        config.base_url,
        "GET",
        f"/me/messages/{email_id}",
        account_id,
        params=params,
    )
    if not result:
        raise ValueError(f"Email with ID {email_id} not found")

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

    if "body" in result:
        del result["body"]

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
    to: list[str] | None = None,
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    if not to and not cc and not bcc:
        raise ValueError("At least one recipient is required (--to, --cc, or --bcc)")

    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)

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
            path = pl.Path(file_path).expanduser().resolve()
            content_bytes = path.read_bytes()
            att_size = len(content_bytes)
            att_name = path.name

            if att_size < LARGE_ATTACHMENT_THRESHOLD:
                small_attachments.append(
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": att_name,
                        "contentBytes": base64.b64encode(content_bytes).decode("utf-8"),
                    }
                )
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

    result = graph.request(
        client,
        config.cache_file,
        config.scopes,
        settings,
        config.base_url,
        "POST",
        "/me/messages",
        account_id,
        json=message,
    )
    if not result:
        raise ValueError("Failed to create email draft")

    message_id = result["id"]

    for att in large_attachments:
        graph.upload_large_mail_attachment(
            client,
            config.cache_file,
            config.scopes,
            settings,
            config.base_url,
            config.upload_chunk_size,
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

    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)

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
            path = pl.Path(file_path).expanduser().resolve()
            content_bytes = path.read_bytes()
            att_size = len(content_bytes)
            att_name = path.name

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

    if not has_large_attachments:
        if processed_attachments:
            message["attachments"] = [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": att["name"],
                    "contentBytes": base64.b64encode(att["content_bytes"]).decode("utf-8"),
                }
                for att in processed_attachments
            ]
        graph.request(
            client,
            config.cache_file,
            config.scopes,
            settings,
            config.base_url,
            "POST",
            "/me/sendMail",
            account_id,
            json={"message": message},
        )
        return {"status": "sent"}

    result = graph.request(
        client,
        config.cache_file,
        config.scopes,
        settings,
        config.base_url,
        "POST",
        "/me/messages",
        account_id,
        json=message,
    )
    if not result:
        raise ValueError("Failed to create email draft")

    message_id = result["id"]

    for att in processed_attachments:
        if att["size"] >= LARGE_ATTACHMENT_THRESHOLD:
            graph.upload_large_mail_attachment(
                client,
                config.cache_file,
                config.scopes,
                settings,
                config.base_url,
                config.upload_chunk_size,
                message_id,
                att["name"],
                att["content_bytes"],
                account_id,
                att["content_type"] if "content_type" in att else "application/octet-stream",
            )
        else:
            small_att = {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": att["name"],
                "contentBytes": base64.b64encode(att["content_bytes"]).decode("utf-8"),
            }
            graph.request(
                client,
                config.cache_file,
                config.scopes,
                settings,
                config.base_url,
                "POST",
                f"/me/messages/{message_id}/attachments",
                account_id,
                json=small_att,
            )

    graph.request(
        client,
        config.cache_file,
        config.scopes,
        settings,
        config.base_url,
        "POST",
        f"/me/messages/{message_id}/send",
        account_id,
    )
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
) -> dict[str, str]:
    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)
    create_endpoint = "createReplyAll" if reply_all else "createReply"
    reply_endpoint = "replyAll" if reply_all else "reply"

    if attachments:
        draft = graph.request(
            client,
            config.cache_file,
            config.scopes,
            settings,
            config.base_url,
            "POST",
            f"/me/messages/{email_id}/{create_endpoint}",
            account_id,
        )
        if not draft or "id" not in draft:
            raise ValueError("Failed to create reply draft")

        draft_id = draft["id"]

        graph.request(
            client,
            config.cache_file,
            config.scopes,
            settings,
            config.base_url,
            "PATCH",
            f"/me/messages/{draft_id}",
            account_id,
            json={"body": {"contentType": "Text", "content": body}},
        )

        for file_path in attachments:
            path = pl.Path(file_path).expanduser().resolve()
            content_bytes = path.read_bytes()
            att_size = len(content_bytes)
            att_name = path.name

            if att_size < LARGE_ATTACHMENT_THRESHOLD:
                attachment = {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": att_name,
                    "contentBytes": base64.b64encode(content_bytes).decode("utf-8"),
                }
                graph.request(
                    client,
                    config.cache_file,
                    config.scopes,
                    settings,
                    config.base_url,
                    "POST",
                    f"/me/messages/{draft_id}/attachments",
                    account_id,
                    json=attachment,
                )
            else:
                graph.upload_large_mail_attachment(
                    client,
                    config.cache_file,
                    config.scopes,
                    settings,
                    config.base_url,
                    config.upload_chunk_size,
                    draft_id,
                    att_name,
                    content_bytes,
                    account_id,
                    "application/octet-stream",
                )

        graph.request(
            client,
            config.cache_file,
            config.scopes,
            settings,
            config.base_url,
            "POST",
            f"/me/messages/{draft_id}/send",
            account_id,
        )
        return {"status": "sent"}
    else:
        endpoint = f"/me/messages/{email_id}/{reply_endpoint}"
        payload = {"message": {"body": {"contentType": "Text", "content": body}}}
        graph.request(
            client,
            config.cache_file,
            config.scopes,
            settings,
            config.base_url,
            "POST",
            endpoint,
            account_id,
            json=payload,
        )
        return {"status": "sent"}


def get_attachment(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    email_id: str,
    attachment_id: str,
    save_path: str,
) -> dict[str, Any]:
    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)
    result = graph.request(
        client,
        config.cache_file,
        config.scopes,
        settings,
        config.base_url,
        "GET",
        f"/me/messages/{email_id}/attachments/{attachment_id}",
        account_id,
    )

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
    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)
    endpoint = _resolve_mail_endpoint(config, folder)
    return _search_mailbox_messages(config, client, account_id, endpoint, query, limit)


def update_email(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    email_id: str,
    is_read: bool | None = None,
    categories: list[str] | None = None,
) -> dict[str, Any]:
    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)

    updates = {}
    if is_read is not None:
        updates["isRead"] = is_read
    if categories is not None:
        updates["categories"] = categories

    if not updates:
        raise ValueError("Must specify at least one field to update (is_read or categories)")

    result = graph.request(
        client,
        config.cache_file,
        config.scopes,
        settings,
        config.base_url,
        "PATCH",
        f"/me/messages/{email_id}",
        account_id,
        json=updates,
    )
    return result or {"status": "updated", "email_id": email_id}
