"""Email-related tools for Microsoft MCP"""

import base64
import pathlib as pl
from typing import Any
from mcp.server.fastmcp import Context
from . import graph, auth
from .auth_tools import mcp  # Use the shared MCP instance
from .context import MicrosoftContext


def _remove_attachment_bytes(result: dict[str, Any]) -> None:
    """Remove contentBytes from attachments to reduce response size"""
    if "attachments" in result and result["attachments"]:
        for attachment in result["attachments"]:
            if "contentBytes" in attachment:
                del attachment["contentBytes"]


@mcp.tool()
def list_emails(
    ctx: Context,
    account_email: str,
    folder: str = "inbox",
    limit: int = 10,
    include_body: bool = True,
) -> list[dict[str, Any]]:
    """folder: 'inbox', 'sent', 'drafts', 'deleted', 'junk', 'archive' (case-insensitive)"""
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, context.settings)

    folder_path = context.folders.get(folder.casefold(), folder)

    if include_body:
        select_fields = "id,subject,from,toRecipients,ccRecipients,receivedDateTime,hasAttachments,body,conversationId,isRead"
    else:
        select_fields = "id,subject,from,toRecipients,receivedDateTime,hasAttachments,conversationId,isRead"

    params = {
        "$top": min(limit, 100),
        "$select": select_fields,
        "$orderby": "receivedDateTime desc",
    }

    emails = list(
        graph.request_paginated(
            context.http_client,
            context.cache_file,
            context.scopes,
            context.base_url,
            f"/me/mailFolders/{folder_path}/messages",
            account_id,
            params=params,
            limit=limit,
        )
    )

    return emails


@mcp.tool()
def get_email(
    ctx: Context,
    email_id: str,
    account_email: str,
    include_body: bool = True,
    include_attachments: bool = True,
    save_to_file: str | None = None,
) -> dict[str, Any]:
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, context.settings)
    params = {}
    if include_attachments:
        params["$expand"] = "attachments($select=id,name,size,contentType)"

    result = graph.request(
        context.http_client, context.cache_file, context.scopes, context.base_url, "GET", f"/me/messages/{email_id}", account_id, params=params
    )
    if not result:
        raise ValueError(f"Email with ID {email_id} not found")

    body_max_length = 25000
    if include_body and "body" in result and "content" in result["body"]:
        content = result["body"]["content"]
        if len(content) > body_max_length:
            result["body"]["content"] = content[:body_max_length] + f"\n\n[Content truncated - {len(content)} total characters]"
            result["body"]["truncated"] = True
            result["body"]["total_length"] = len(content)
    elif not include_body and "body" in result:
        del result["body"]

    _remove_attachment_bytes(result)

    if save_to_file is not None:
        file_path = save_to_file if save_to_file else f"/tmp/email_{email_id[:8]}.txt"
        path = pl.Path(file_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        content_lines = [
            f"From: {result.get('from', {}).get('emailAddress', {}).get('address', 'unknown')}",
            f"Subject: {result.get('subject', 'No subject')}",
            f"Date: {result.get('receivedDateTime', 'unknown')}",
            f"To: {', '.join([r.get('emailAddress', {}).get('address', '') for r in result.get('toRecipients', [])])}",
        ]

        if result.get("ccRecipients"):
            content_lines.append(f"Cc: {', '.join([r.get('emailAddress', {}).get('address', '') for r in result.get('ccRecipients', [])])}")

        content_lines.extend(["", "=" * 80, "", result.get("body", {}).get("content", "No content")])

        path.write_text("\n".join(content_lines))
        result["saved_to"] = str(path)
        result["saved_size"] = path.stat().st_size

    return result


@mcp.tool()
def create_email_draft(
    ctx: Context,
    account_email: str,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    """to/cc: list of email addresses. attachments: list of file paths"""
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, context.settings)

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
        context.http_client, context.cache_file, context.scopes, context.base_url, "POST", "/me/messages", account_id, json=message
    )
    if not result:
        raise ValueError("Failed to create email draft")

    message_id = result["id"]

    for att in large_attachments:
        graph.upload_large_mail_attachment(
            context.http_client,
            context.cache_file,
            context.scopes,
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
    account_email: str,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    attachments: list[str] | None = None,
) -> dict[str, str]:
    """to/cc: list of email addresses. attachments: list of file paths"""
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, context.settings)

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
            context.http_client, context.cache_file, context.scopes, context.base_url, "POST", "/me/messages", account_id, json=message
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
                    context.base_url,
                    "POST",
                    f"/me/messages/{message_id}/attachments",
                    account_id,
                    json=small_att,
                )

        graph.request(
            context.http_client, context.cache_file, context.scopes, context.base_url, "POST", f"/me/messages/{message_id}/send", account_id
        )
        return {"status": "sent"}
    else:
        graph.request(
            context.http_client,
            context.cache_file,
            context.scopes,
            context.base_url,
            "POST",
            "/me/sendMail",
            account_id,
            json={"message": message},
        )
        return {"status": "sent"}


@mcp.tool()
def reply_to_email(
    ctx: Context, account_email: str, email_id: str, body: str, attachments: list[str] | None = None, reply_all: bool = False
) -> dict[str, str]:
    """attachments: list of file paths"""
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, context.settings)
    create_endpoint = "createReplyAll" if reply_all else "createReply"
    reply_endpoint = "replyAll" if reply_all else "reply"

    if attachments:
        draft = graph.request(
            context.http_client,
            context.cache_file,
            context.scopes,
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
                    context.base_url,
                    context.upload_chunk_size,
                    draft_id,
                    att_name,
                    content_bytes,
                    account_id,
                    "application/octet-stream",
                )

        graph.request(
            context.http_client, context.cache_file, context.scopes, context.base_url, "POST", f"/me/messages/{draft_id}/send", account_id
        )
        return {"status": "sent"}
    else:
        endpoint = f"/me/messages/{email_id}/{reply_endpoint}"
        payload = {"message": {"body": {"contentType": "Text", "content": body}}}
        graph.request(context.http_client, context.cache_file, context.scopes, context.base_url, "POST", endpoint, account_id, json=payload)
        return {"status": "sent"}


@mcp.tool()
def get_attachment(ctx: Context, email_id: str, attachment_id: str, save_path: str, account_email: str) -> dict[str, Any]:
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, context.settings)
    result = graph.request(
        context.http_client,
        context.cache_file,
        context.scopes,
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
    query: str,
    account_email: str,
    limit: int = 50,
    folder: str | None = None,
) -> list[dict[str, Any]]:
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, context.settings)
    if folder:
        # For folder-specific search, use the traditional endpoint
        folder_path = context.folders.get(folder.casefold(), folder)
        endpoint = f"/me/mailFolders/{folder_path}/messages"

        params = {
            "$search": f'"{query}"',
            "$top": min(limit, 100),
            "$select": "id,subject,from,toRecipients,receivedDateTime,hasAttachments,body,conversationId,isRead",
        }

        return list(
            graph.request_paginated(
                context.http_client, context.cache_file, context.scopes, context.base_url, endpoint, account_id, params=params, limit=limit
            )
        )

    return list(
        graph.search_query(context.http_client, context.cache_file, context.scopes, context.base_url, query, ["message"], account_id, limit)
    )


@mcp.tool()
def update_email(
    ctx: Context, email_id: str, account_email: str, is_read: bool | None = None, categories: list[str] | None = None
) -> dict[str, Any]:
    """Mark email as read/unread or add categories"""
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, context.settings)

    updates = {}
    if is_read is not None:
        updates["isRead"] = is_read
    if categories is not None:
        updates["categories"] = categories

    if not updates:
        raise ValueError("Must specify at least one field to update (is_read or categories)")

    result = graph.request(
        context.http_client, context.cache_file, context.scopes, context.base_url, "PATCH", f"/me/messages/{email_id}", account_id, json=updates
    )
    return result or {"status": "updated", "email_id": email_id}
