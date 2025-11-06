"""Email-related tools for Microsoft MCP"""

import base64
import pathlib as pl
from typing import Any
from . import graph
from .auth_tools import mcp  # Use the shared MCP instance

FOLDERS = {
    k.casefold(): v
    for k, v in {
        "inbox": "inbox",
        "sent": "sentitems",
        "drafts": "drafts",
        "deleted": "deleteditems",
        "junk": "junkemail",
        "archive": "archive",
    }.items()
}


@mcp.tool()
def list_emails(
    account_id: str,
    folder: str = "inbox",
    limit: int = 10,
    include_body: bool = True,
) -> list[dict[str, Any]]:

    folder_path = FOLDERS.get(folder.casefold(), folder)

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
            f"/me/mailFolders/{folder_path}/messages",
            account_id,
            params=params,
            limit=limit,
        )
    )

    return emails


@mcp.tool()
def get_email(
    email_id: str,
    account_id: str,
    include_body: bool = True,
    body_max_length: int = 50000,
    include_attachments: bool = True,
) -> dict[str, Any]:

    params = {}
    if include_attachments:
        params["$expand"] = "attachments($select=id,name,size,contentType)"

    result = graph.request("GET", f"/me/messages/{email_id}", account_id, params=params)
    if not result:
        raise ValueError(f"Email with ID {email_id} not found")

    # Truncate body if needed
    if include_body and "body" in result and "content" in result["body"]:
        content = result["body"]["content"]
        if len(content) > body_max_length:
            result["body"]["content"] = content[:body_max_length] + f"\n\n[Content truncated - {len(content)} total characters]"
            result["body"]["truncated"] = True
            result["body"]["total_length"] = len(content)
    elif not include_body and "body" in result:
        del result["body"]

    # Remove attachment content bytes to reduce size
    if "attachments" in result and result["attachments"]:
        for attachment in result["attachments"]:
            if "contentBytes" in attachment:
                del attachment["contentBytes"]

    return result


@mcp.tool()
def create_email_draft(
    account_id: str,
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    attachments: str | None = None,
) -> dict[str, Any]:
    # Handle both single and comma-separated email addresses
    to_list = [addr.strip() for addr in to.split(",") if addr.strip()] if "," in to else [to]

    message = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": addr}} for addr in to_list],
    }

    if cc:
        cc_list = [addr.strip() for addr in cc.split(",") if addr.strip()] if "," in cc else [cc]
        message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc_list]

    small_attachments = []
    large_attachments = []

    if attachments:
        # Handle both single and comma-separated paths
        attachment_paths = [path.strip() for path in attachments.split(",") if path.strip()] if "," in attachments else [attachments]
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

    result = graph.request("POST", "/me/messages", account_id, json=message)
    if not result:
        raise ValueError("Failed to create email draft")

    message_id = result["id"]

    for att in large_attachments:
        graph.upload_large_mail_attachment(
            message_id,
            att["name"],
            att["content_bytes"],
            account_id,
            att.get("content_type", "application/octet-stream"),
        )

    return result


@mcp.tool()
def send_email(
    account_id: str,
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    attachments: str | None = None,
) -> dict[str, str]:
    # Handle both single and comma-separated email addresses
    to_list = [addr.strip() for addr in to.split(",") if addr.strip()] if "," in to else [to]

    message = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": addr}} for addr in to_list],
    }

    if cc:
        cc_list = [addr.strip() for addr in cc.split(",") if addr.strip()] if "," in cc else [cc]
        message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc_list]

    # Check if we have large attachments
    has_large_attachments = False
    processed_attachments = []

    if attachments:
        # Handle both single and comma-separated paths
        attachment_paths = [path.strip() for path in attachments.split(",") if path.strip()] if "," in attachments else [attachments]
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
        graph.request("POST", "/me/sendMail", account_id, json={"message": message})
        return {"status": "sent"}
    elif has_large_attachments:
        # Create draft first, then add large attachments, then send
        # We need to handle large attachments manually here
        to_list = [addr.strip() for addr in to.split(",") if addr.strip()] if "," in to else [to]
        message = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to_list],
        }
        if cc:
            cc_list = [cc] if isinstance(cc, str) else cc
            message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc_list]

        result = graph.request("POST", "/me/messages", account_id, json=message)
        if not result:
            raise ValueError("Failed to create email draft")

        message_id = result["id"]

        for att in processed_attachments:
            if att["size"] >= 3 * 1024 * 1024:
                graph.upload_large_mail_attachment(
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
                    "POST",
                    f"/me/messages/{message_id}/attachments",
                    account_id,
                    json=small_att,
                )

        graph.request("POST", f"/me/messages/{message_id}/send", account_id)
        return {"status": "sent"}
    else:
        graph.request("POST", "/me/sendMail", account_id, json={"message": message})
        return {"status": "sent"}


@mcp.tool()
def reply_to_email(account_id: str, email_id: str, body: str, attachments: str | None = None, reply_all: bool = False) -> dict[str, str]:
    create_endpoint = "createReplyAll" if reply_all else "createReply"
    reply_endpoint = "replyAll" if reply_all else "reply"

    if attachments:
        draft = graph.request("POST", f"/me/messages/{email_id}/{create_endpoint}", account_id)
        if not draft or "id" not in draft:
            raise ValueError(f"Failed to create reply draft")

        draft_id = draft["id"]

        graph.request(
            "PATCH",
            f"/me/messages/{draft_id}",
            account_id,
            json={"body": {"contentType": "Text", "content": body}},
        )

        attachment_paths = [path.strip() for path in attachments.split(",") if path.strip()] if "," in attachments else [attachments]
        for file_path in attachment_paths:
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
                    "POST",
                    f"/me/messages/{draft_id}/attachments",
                    account_id,
                    json=attachment,
                )
            else:
                graph.upload_large_mail_attachment(
                    draft_id,
                    att_name,
                    content_bytes,
                    account_id,
                    "application/octet-stream",
                )

        graph.request("POST", f"/me/messages/{draft_id}/send", account_id)
        return {"status": "sent"}
    else:
        endpoint = f"/me/messages/{email_id}/{reply_endpoint}"
        payload = {"message": {"body": {"contentType": "Text", "content": body}}}
        graph.request("POST", endpoint, account_id, json=payload)
        return {"status": "sent"}


@mcp.tool()
def get_attachment(email_id: str, attachment_id: str, save_path: str, account_id: str) -> dict[str, Any]:
    result = graph.request("GET", f"/me/messages/{email_id}/attachments/{attachment_id}", account_id)

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
    query: str,
    account_id: str,
    limit: int = 50,
    folder: str | None = None,
) -> list[dict[str, Any]]:

    if folder:
        # For folder-specific search, use the traditional endpoint
        folder_path = FOLDERS.get(folder.casefold(), folder)
        endpoint = f"/me/mailFolders/{folder_path}/messages"

        params = {
            "$search": f'"{query}"',
            "$top": min(limit, 100),
            "$select": "id,subject,from,toRecipients,receivedDateTime,hasAttachments,body,conversationId,isRead",
        }

        return list(graph.request_paginated(endpoint, account_id, params=params, limit=limit))

    return list(graph.search_query(query, ["message"], account_id, limit))
