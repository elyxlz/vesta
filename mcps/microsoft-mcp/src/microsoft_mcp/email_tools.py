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
    """List emails from specified folder"""

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
    include_attachments: bool = True,
    save_to_file: str | None = None,
) -> dict[str, Any]:
    """Get email details with size limits

    Args:
        email_id: The email ID
        account_id: The account ID
        include_body: Whether to include the email body (default: True)
        include_attachments: Whether to include attachment metadata (default: True)
        save_to_file: Optional file path to save email (defaults to /tmp/email_{email_id}.txt if set to empty string)
    """

    params = {}
    if include_attachments:
        params["$expand"] = "attachments($select=id,name,size,contentType)"

    result = graph.request("GET", f"/me/messages/{email_id}", account_id, params=params)
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

    # Remove attachment content bytes to reduce size
    if "attachments" in result and result["attachments"]:
        for attachment in result["attachments"]:
            if "contentBytes" in attachment:
                del attachment["contentBytes"]

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

        if result.get('ccRecipients'):
            content_lines.append(f"Cc: {', '.join([r.get('emailAddress', {}).get('address', '') for r in result.get('ccRecipients', [])])}")

        content_lines.extend(["", "=" * 80, "", result.get('body', {}).get('content', 'No content')])

        path.write_text("\n".join(content_lines))
        result["saved_to"] = str(path)
        result["saved_size"] = path.stat().st_size

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
    """Create an email draft with file path(s) as attachments

    Args:
        account_id: The account ID
        to: Email addresses - accepts:
            - Single email: "user@example.com"
            - Multiple emails: "user1@example.com,user2@example.com"
        subject: Email subject
        body: Email body text
        cc: CC email addresses (optional) - accepts:
            - Single email: "user@example.com"
            - Multiple emails: "user1@example.com,user2@example.com"
        attachments: File paths (optional) - accepts:
            - Single path: "/path/to/file.pdf"
            - Multiple paths: "/path/to/file1.pdf,/path/to/file2.docx"
    """
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
    """Send an email immediately with file path(s) as attachments

    Args:
        account_id: The account ID
        to: Email addresses - accepts:
            - Single email: "user@example.com"
            - Multiple emails: "user1@example.com,user2@example.com"
        subject: Email subject
        body: Email body text
        cc: CC email addresses (optional) - accepts:
            - Single email: "user@example.com"
            - Multiple emails: "user1@example.com,user2@example.com"
        attachments: File paths (optional) - accepts:
            - Single path: "/path/to/file.pdf"
            - Multiple paths: "/path/to/file1.pdf,/path/to/file2.docx"
    """
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
def update_email(email_id: str, updates: dict[str, Any], account_id: str) -> dict[str, Any]:
    """Update email properties (isRead, categories, flag, etc.)"""
    result = graph.request("PATCH", f"/me/messages/{email_id}", account_id, json=updates)
    if not result:
        raise ValueError(f"Failed to update email {email_id} - no response")
    return result


@mcp.tool()
def delete_email(email_id: str, account_id: str) -> dict[str, str]:
    """Delete an email"""
    graph.request("DELETE", f"/me/messages/{email_id}", account_id)
    return {"status": "deleted"}


@mcp.tool()
def move_email(email_id: str, destination_folder: str, account_id: str) -> dict[str, Any]:
    """Move email to another folder"""
    folder_path = FOLDERS.get(destination_folder.casefold(), destination_folder)

    folders = graph.request("GET", "/me/mailFolders", account_id)
    folder_id = None

    if not folders:
        raise ValueError("Failed to retrieve mail folders")
    if "value" not in folders:
        raise ValueError(f"Unexpected folder response structure: {folders}")

    for folder in folders["value"]:
        if folder["displayName"].lower() == folder_path.lower():
            folder_id = folder["id"]
            break

    if not folder_id:
        raise ValueError(f"Folder '{destination_folder}' not found")

    payload = {"destinationId": folder_id}
    result = graph.request("POST", f"/me/messages/{email_id}/move", account_id, json=payload)
    if not result:
        raise ValueError("Failed to move email - no response from server")
    if "id" not in result:
        raise ValueError(f"Failed to move email - unexpected response: {result}")
    return {"status": "moved", "new_id": result["id"]}


@mcp.tool()
def reply_to_email(account_id: str, email_id: str, body: str, attachments: str | None = None) -> dict[str, str]:
    """Reply to an email (sender only) with optional attachments

    Args:
        account_id: The account ID
        email_id: The email ID to reply to
        body: Reply message body
        attachments: File paths for attachments (optional) - accepts:
            - Single path: "/path/to/file.pdf"
            - Multiple paths: "/path/to/file1.pdf,/path/to/file2.docx"
    """
    # If we have attachments, we need to create a draft first, add attachments, then send
    if attachments:
        # Get the original message to extract sender
        original = graph.request(
            "GET",
            f"/me/messages/{email_id}",
            account_id,
            params={"$select": "from,subject,conversationId"},
        )
        if not original:
            raise ValueError(f"Email with ID {email_id} not found")

        # Create reply draft
        draft = graph.request("POST", f"/me/messages/{email_id}/createReply", account_id)
        if not draft or "id" not in draft:
            raise ValueError("Failed to create reply draft")

        draft_id = draft["id"]

        # Update draft body
        graph.request(
            "PATCH",
            f"/me/messages/{draft_id}",
            account_id,
            json={"body": {"contentType": "Text", "content": body}},
        )

        # Add attachments
        attachment_paths = [path.strip() for path in attachments.split(",") if path.strip()] if "," in attachments else [attachments]
        for file_path in attachment_paths:
            path = pl.Path(file_path).expanduser().resolve()
            content_bytes = path.read_bytes()
            att_size = len(content_bytes)
            att_name = path.name

            if att_size < 3 * 1024 * 1024:
                # Small attachment
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
                # Large attachment
                graph.upload_large_mail_attachment(
                    draft_id,
                    att_name,
                    content_bytes,
                    account_id,
                    "application/octet-stream",
                )

        # Send the draft
        graph.request("POST", f"/me/messages/{draft_id}/send", account_id)
        return {"status": "sent"}
    else:
        # Simple reply without attachments
        endpoint = f"/me/messages/{email_id}/reply"
        payload = {"message": {"body": {"contentType": "Text", "content": body}}}
        graph.request("POST", endpoint, account_id, json=payload)
        return {"status": "sent"}


@mcp.tool()
def reply_all_email(account_id: str, email_id: str, body: str, attachments: str | None = None) -> dict[str, str]:
    """Reply to all recipients of an email with optional attachments

    Args:
        account_id: The account ID
        email_id: The email ID to reply to
        body: Reply message body
        attachments: File paths for attachments (optional) - accepts:
            - Single path: "/path/to/file.pdf"
            - Multiple paths: "/path/to/file1.pdf,/path/to/file2.docx"
    """
    # If we have attachments, we need to create a draft first, add attachments, then send
    if attachments:
        # Get the original message to extract recipients
        original = graph.request(
            "GET",
            f"/me/messages/{email_id}",
            account_id,
            params={"$select": "from,toRecipients,ccRecipients,subject,conversationId"},
        )
        if not original:
            raise ValueError(f"Email with ID {email_id} not found")

        # Create reply all draft
        draft = graph.request("POST", f"/me/messages/{email_id}/createReplyAll", account_id)
        if not draft or "id" not in draft:
            raise ValueError("Failed to create reply all draft")

        draft_id = draft["id"]

        # Update draft body
        graph.request(
            "PATCH",
            f"/me/messages/{draft_id}",
            account_id,
            json={"body": {"contentType": "Text", "content": body}},
        )

        # Add attachments
        attachment_paths = [path.strip() for path in attachments.split(",") if path.strip()] if "," in attachments else [attachments]
        for file_path in attachment_paths:
            path = pl.Path(file_path).expanduser().resolve()
            content_bytes = path.read_bytes()
            att_size = len(content_bytes)
            att_name = path.name

            if att_size < 3 * 1024 * 1024:
                # Small attachment
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
                # Large attachment
                graph.upload_large_mail_attachment(
                    draft_id,
                    att_name,
                    content_bytes,
                    account_id,
                    "application/octet-stream",
                )

        # Send the draft
        graph.request("POST", f"/me/messages/{draft_id}/send", account_id)
        return {"status": "sent"}
    else:
        # Simple reply all without attachments
        endpoint = f"/me/messages/{email_id}/replyAll"
        payload = {"message": {"body": {"contentType": "Text", "content": body}}}
        graph.request("POST", endpoint, account_id, json=payload)
        return {"status": "sent"}


@mcp.tool()
def get_attachment(email_id: str, attachment_id: str, save_path: str, account_id: str) -> dict[str, Any]:
    """Download email attachment to a specified file path"""
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
    """Search emails using the modern search API."""

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
