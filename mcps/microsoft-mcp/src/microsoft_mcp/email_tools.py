"""Email-related tools for Microsoft MCP"""

import base64
import pathlib as pl
from datetime import datetime, UTC
from typing import Any
from mcp.server.fastmcp import Context
from . import graph, auth
from .auth_tools import mcp  # Use the shared MCP instance
from .context import MicrosoftContext

EMAIL_SAVE_SUBDIR = "emails"
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


def _remove_attachment_bytes(result: dict[str, Any]) -> None:
    """Remove contentBytes from attachments to reduce response size"""
    if "attachments" in result and result["attachments"]:
        for attachment in result["attachments"]:
            if "contentBytes" in attachment:
                del attachment["contentBytes"]


def _sanitize_filename(value: str) -> str:
    """Return a filesystem-safe fragment"""
    sanitized = "".join(char if char.isalnum() else "_" for char in value or "")
    sanitized = sanitized.strip("_")
    return sanitized or "email"


def _prepare_email_output_path(
    context: MicrosoftContext,
    email_id: str,
    subject: str | None,
    override_path: str | None,
) -> pl.Path:
    """Determine where to persist the email content"""
    if override_path:
        path = pl.Path(override_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    base_dir = context.cache_file.parent / EMAIL_SAVE_SUBDIR
    base_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    subject_fragment = _sanitize_filename(subject or "")
    id_fragment = _sanitize_filename(email_id)[:32]
    filename = f"{timestamp}_{subject_fragment[:40]}_{id_fragment}.txt".strip("_")

    return base_dir / filename


def _scrub_email_snapshot(record: dict[str, Any]) -> None:
    """Ensure email summaries never leak body content"""
    if "body" in record:
        del record["body"]
    if "bodyPreview" in record:
        record.setdefault("preview", record.pop("bodyPreview"))


def _resolve_mail_endpoint(context: MicrosoftContext, folder: str | None) -> str:
    """Return the correct Graph endpoint for mailbox or folder scopes"""
    if folder:
        folder_path = context.folders.get(folder.casefold(), folder)
        return f"/me/mailFolders/{folder_path}/messages"
    return "/me/messages"


def _search_mailbox_messages(
    context: MicrosoftContext,
    account_id: str,
    endpoint: str,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Execute a mailbox search using the Graph messages endpoint"""
    params = {
        "$search": f'"{query}"',
        "$top": min(limit, 100),
        "$select": EMAIL_SNAPSHOT_SELECT,
    }
    emails = list(
        graph.request_paginated(
            context.http_client,
            context.cache_file,
            context.scopes,
            context.settings,
            context.base_url,
            endpoint,
            account_id,
            params=params,
            limit=limit,
        )
    )
    for email in emails:
        _scrub_email_snapshot(email)
    return emails


@mcp.tool()
def list_emails(
    ctx: Context,
    *,
    account_email: str,
    folder: str = "inbox",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """List email metadata. Bodies are never returned."""
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, settings=context.settings)

    folder_path = context.folders.get(folder.casefold(), folder)

    params = {
        "$top": min(limit, 100),
        "$select": EMAIL_SNAPSHOT_SELECT,
        "$orderby": "receivedDateTime desc",
    }

    emails = list(
        graph.request_paginated(
            context.http_client,
            context.cache_file,
            context.scopes,
            context.settings,
            context.base_url,
            f"/me/mailFolders/{folder_path}/messages",
            account_id,
            params=params,
            limit=limit,
        )
    )

    for email in emails:
        _scrub_email_snapshot(email)

    return emails


@mcp.tool()
def get_email(
    ctx: Context,
    *,
    account_email: str,
    email_id: str,
    include_attachments: bool = True,
    save_to_file: str | None = None,
) -> dict[str, Any]:
    """Get email metadata. Body content is always saved to disk and never returned."""
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, settings=context.settings)
    params: dict[str, Any] = {
        "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,hasAttachments,conversationId,isRead,body,bodyPreview",
    }
    if include_attachments:
        params["$expand"] = "attachments($select=id,name,size,contentType)"

    result = graph.request(
        context.http_client,
        context.cache_file,
        context.scopes,
        context.settings,
        context.base_url,
        "GET",
        f"/me/messages/{email_id}",
        account_id,
        params=params,
    )
    if not result:
        raise ValueError(f"Email with ID {email_id} not found")

    full_body_content = (result.get("body") or {}).get("content") or ""
    _remove_attachment_bytes(result)

    save_path = _prepare_email_output_path(context, email_id, result.get("subject"), save_to_file)
    content_lines = [
        f"From: {result.get('from', {}).get('emailAddress', {}).get('address', 'unknown')}",
        f"Subject: {result.get('subject', 'No subject')}",
        f"Date: {result.get('receivedDateTime', 'unknown')}",
        f"To: {', '.join([r.get('emailAddress', {}).get('address', '') for r in result.get('toRecipients', [])])}",
    ]

    if result.get("ccRecipients"):
        content_lines.append(f"Cc: {', '.join([r.get('emailAddress', {}).get('address', '') for r in result.get('ccRecipients', [])])}")

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


@mcp.tool()
def create_email_draft(
    ctx: Context,
    *,
    account_email: str,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    """to/cc: list of email addresses. attachments: list of file paths"""
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, settings=context.settings)

    message = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
    }

    if cc:
        message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]

    small_attachments = []
    large_attachments = []

    if attachments:
        attachment_paths = attachments
        for file_path in attachment_paths:
            path = pl.Path(file_path).expanduser().resolve()
            content_bytes = path.read_bytes()
            att_size = len(content_bytes)
            att_name = path.name

            if att_size < 3 * 1024 * 1024:
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
        context.http_client,
        context.cache_file,
        context.scopes,
        context.settings,
        context.base_url,
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
            context.http_client,
            context.cache_file,
            context.scopes,
            context.settings,
            context.base_url,
            context.upload_chunk_size,
            message_id,
            att["name"],
            att["content_bytes"],
            account_id,
            att.get("content_type", "application/octet-stream"),
        )

    return result


@mcp.tool()
def send_email(
    ctx: Context,
    *,
    account_email: str,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    attachments: list[str] | None = None,
) -> dict[str, str]:
    """to/cc: list of email addresses. attachments: list of file paths"""
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, settings=context.settings)

    message = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
    }

    if cc:
        message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]

    has_large_attachments = False
    processed_attachments = []

    if attachments:
        attachment_paths = attachments
        for file_path in attachment_paths:
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

            if att_size >= 3 * 1024 * 1024:
                has_large_attachments = True

    if not has_large_attachments and processed_attachments:
        message["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": att["name"],
                "contentBytes": base64.b64encode(att["content_bytes"]).decode("utf-8"),
            }
            for att in processed_attachments
        ]
        graph.request(
            context.http_client,
            context.cache_file,
            context.scopes,
            context.settings,
            context.base_url,
            "POST",
            "/me/sendMail",
            account_id,
            json={"message": message},
        )
        return {"status": "sent"}
    elif has_large_attachments:
        message = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
        }
        if cc:
            message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]

        result = graph.request(
            context.http_client,
            context.cache_file,
            context.scopes,
            context.settings,
            context.base_url,
            "POST",
            "/me/messages",
            account_id,
            json=message,
        )
        if not result:
            raise ValueError("Failed to create email draft")

        message_id = result["id"]

        for att in processed_attachments:
            if att["size"] >= 3 * 1024 * 1024:
                graph.upload_large_mail_attachment(
                    context.http_client,
                    context.cache_file,
                    context.scopes,
                    context.settings,
                    context.base_url,
                    context.upload_chunk_size,
                    message_id,
                    att["name"],
                    att["content_bytes"],
                    account_id,
                    att.get("content_type", "application/octet-stream"),
                )
            else:
                small_att = {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": att["name"],
                    "contentBytes": base64.b64encode(att["content_bytes"]).decode("utf-8"),
                }
                graph.request(
                    context.http_client,
                    context.cache_file,
                    context.scopes,
                    context.settings,
                    context.base_url,
                    "POST",
                    f"/me/messages/{message_id}/attachments",
                    account_id,
                    json=small_att,
                )

        graph.request(
            context.http_client,
            context.cache_file,
            context.scopes,
            context.settings,
            context.base_url,
            "POST",
            f"/me/messages/{message_id}/send",
            account_id,
        )
        return {"status": "sent"}
    else:
        graph.request(
            context.http_client,
            context.cache_file,
            context.scopes,
            context.settings,
            context.base_url,
            "POST",
            "/me/sendMail",
            account_id,
            json={"message": message},
        )
        return {"status": "sent"}


@mcp.tool()
def reply_to_email(
    ctx: Context,
    *,
    account_email: str,
    email_id: str,
    body: str,
    attachments: list[str] | None = None,
    reply_all: bool = False,
) -> dict[str, str]:
    """attachments: list of file paths"""
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, settings=context.settings)
    create_endpoint = "createReplyAll" if reply_all else "createReply"
    reply_endpoint = "replyAll" if reply_all else "reply"

    if attachments:
        draft = graph.request(
            context.http_client,
            context.cache_file,
            context.scopes,
            context.settings,
            context.base_url,
            "POST",
            f"/me/messages/{email_id}/{create_endpoint}",
            account_id,
        )
        if not draft or "id" not in draft:
            raise ValueError("Failed to create reply draft")

        draft_id = draft["id"]

        graph.request(
            context.http_client,
            context.cache_file,
            context.scopes,
            context.settings,
            context.base_url,
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

            if att_size < 3 * 1024 * 1024:
                attachment = {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": att_name,
                    "contentBytes": base64.b64encode(content_bytes).decode("utf-8"),
                }
                graph.request(
                    context.http_client,
                    context.cache_file,
                    context.scopes,
                    context.settings,
                    context.base_url,
                    "POST",
                    f"/me/messages/{draft_id}/attachments",
                    account_id,
                    json=attachment,
                )
            else:
                graph.upload_large_mail_attachment(
                    context.http_client,
                    context.cache_file,
                    context.scopes,
                    context.settings,
                    context.base_url,
                    context.upload_chunk_size,
                    draft_id,
                    att_name,
                    content_bytes,
                    account_id,
                    "application/octet-stream",
                )

        graph.request(
            context.http_client,
            context.cache_file,
            context.scopes,
            context.settings,
            context.base_url,
            "POST",
            f"/me/messages/{draft_id}/send",
            account_id,
        )
        return {"status": "sent"}
    else:
        endpoint = f"/me/messages/{email_id}/{reply_endpoint}"
        payload = {"message": {"body": {"contentType": "Text", "content": body}}}
        graph.request(
            context.http_client,
            context.cache_file,
            context.scopes,
            context.settings,
            context.base_url,
            "POST",
            endpoint,
            account_id,
            json=payload,
        )
        return {"status": "sent"}


@mcp.tool()
def get_attachment(
    ctx: Context,
    *,
    account_email: str,
    email_id: str,
    attachment_id: str,
    save_path: str,
) -> dict[str, Any]:
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, settings=context.settings)
    result = graph.request(
        context.http_client,
        context.cache_file,
        context.scopes,
        context.settings,
        context.base_url,
        "GET",
        f"/me/messages/{email_id}/attachments/{attachment_id}",
        account_id,
    )

    if not result:
        raise ValueError("Attachment not found")

    if "contentBytes" not in result:
        raise ValueError("Attachment content not available")

    # Save attachment to file
    path = pl.Path(save_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    content_bytes = base64.b64decode(result["contentBytes"])
    path.write_bytes(content_bytes)

    return {
        "name": result.get("name", "unknown"),
        "content_type": result.get("contentType", "application/octet-stream"),
        "size": result.get("size", 0),
        "saved_to": str(path),
    }


@mcp.tool()
def search_emails(
    ctx: Context,
    *,
    account_email: str,
    query: str,
    limit: int = 10,
    folder: str | None = None,
) -> list[dict[str, Any]]:
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, settings=context.settings)
    endpoint = _resolve_mail_endpoint(context, folder)
    return _search_mailbox_messages(context, account_id, endpoint, query, limit)


@mcp.tool()
def update_email(
    ctx: Context,
    *,
    account_email: str,
    email_id: str,
    is_read: bool | None = None,
    categories: list[str] | None = None,
) -> dict[str, Any]:
    """Mark email as read/unread or add categories"""
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, settings=context.settings)

    updates = {}
    if is_read is not None:
        updates["isRead"] = is_read
    if categories is not None:
        updates["categories"] = categories

    if not updates:
        raise ValueError("Must specify at least one field to update (is_read or categories)")

    result = graph.request(
        context.http_client,
        context.cache_file,
        context.scopes,
        context.settings,
        context.base_url,
        "PATCH",
        f"/me/messages/{email_id}",
        account_id,
        json=updates,
    )
    return result or {"status": "updated", "email_id": email_id}
