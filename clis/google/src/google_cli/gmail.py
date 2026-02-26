import base64
import pathlib as pl
from datetime import datetime, UTC
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Any

from . import api
from .config import Config

EMAIL_SAVE_SUBDIR = "emails"
LONG_EMAIL_WARNING_THRESHOLD = 5000


def _sanitize_filename(value: str) -> str:
    sanitized = "".join(char if char.isalnum() else "_" for char in value or "")
    sanitized = sanitized.strip("_")
    return sanitized or "email"


def _prepare_email_output_path(config: Config, message_id: str, subject: str | None, override_path: str | None) -> pl.Path:
    if override_path:
        path = pl.Path(override_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    base_dir = config.data_dir / EMAIL_SAVE_SUBDIR
    base_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    subject_fragment = _sanitize_filename(subject or "")
    id_fragment = _sanitize_filename(message_id)[:32]
    filename = f"{timestamp}_{subject_fragment[:40]}_{id_fragment}.txt".strip("_")
    return base_dir / filename


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _parse_message_snapshot(msg: dict) -> dict:
    headers = msg.get("payload", {}).get("headers", [])
    return {
        "id": msg["id"],
        "threadId": msg.get("threadId"),
        "subject": _get_header(headers, "Subject"),
        "from": _get_header(headers, "From"),
        "to": _get_header(headers, "To"),
        "date": _get_header(headers, "Date"),
        "snippet": msg.get("snippet", ""),
        "labelIds": msg.get("labelIds", []),
    }


def _get_body_text(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        result = _get_body_text(part)
        if result:
            return result

    return ""


def _get_attachments_info(payload: dict) -> list[dict]:
    attachments = []
    for part in payload.get("parts", []):
        if part.get("filename") and part.get("body", {}).get("attachmentId"):
            attachments.append({
                "id": part["body"]["attachmentId"],
                "name": part["filename"],
                "size": part.get("body", {}).get("size", 0),
                "mimeType": part.get("mimeType", "application/octet-stream"),
            })
        if part.get("parts"):
            attachments.extend(_get_attachments_info(part))
    return attachments


def _build_mime_body(body: str, attachments: list[str] | None = None) -> MIMEText | MIMEMultipart:
    if not attachments:
        return MIMEText(body, "plain")
    msg = MIMEMultipart()
    msg.attach(MIMEText(body, "plain"))
    for file_path in attachments:
        path = pl.Path(file_path).expanduser().resolve()
        part = MIMEBase("application", "octet-stream")
        part.set_payload(path.read_bytes())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={path.name}")
        msg.attach(part)
    return msg


def _build_mime_message(to: list[str], subject: str, body: str, cc: list[str] | None = None, attachments: list[str] | None = None) -> str:
    msg = _build_mime_body(body, attachments)
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = ", ".join(cc)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def list_emails(config: Config, *, label: str = "INBOX", limit: int = 10) -> list[dict[str, Any]]:
    service = api.gmail_service(config)
    results = api.retry(lambda: service.users().messages().list(userId="me", labelIds=[label], maxResults=min(limit, 100)).execute())
    messages = results.get("messages", [])

    output = []
    for msg_ref in messages[:limit]:
        msg = api.retry(lambda mid=msg_ref["id"]: service.users().messages().get(userId="me", id=mid, format="metadata", metadataHeaders=["Subject", "From", "To", "Date"]).execute())
        output.append(_parse_message_snapshot(msg))
    return output


def get_email(config: Config, *, message_id: str, include_attachments: bool = True, save_to_file: str | None = None) -> dict[str, Any]:
    service = api.gmail_service(config)
    msg = api.retry(lambda: service.users().messages().get(userId="me", id=message_id, format="full").execute())
    payload = msg.get("payload", {})
    headers = payload.get("headers", [])

    subject = _get_header(headers, "Subject")
    full_body = _get_body_text(payload)

    result: dict[str, Any] = {
        "id": msg["id"],
        "threadId": msg.get("threadId"),
        "subject": subject,
        "from": _get_header(headers, "From"),
        "to": _get_header(headers, "To"),
        "cc": _get_header(headers, "Cc"),
        "date": _get_header(headers, "Date"),
        "snippet": msg.get("snippet", ""),
        "labelIds": msg.get("labelIds", []),
    }

    if include_attachments:
        result["attachments"] = _get_attachments_info(payload)

    save_path = _prepare_email_output_path(config, message_id, subject, save_to_file)
    content_lines = [
        f"From: {result['from']}",
        f"Subject: {subject}",
        f"Date: {result['date']}",
        f"To: {result['to']}",
    ]
    if result["cc"]:
        content_lines.append(f"Cc: {result['cc']}")
    content_lines.extend(["", "=" * 80, "", full_body])
    save_path.write_text("\n".join(content_lines), encoding="utf-8")

    result["body_saved_to"] = str(save_path)
    result["body_saved_size"] = save_path.stat().st_size
    result["body_length"] = len(full_body)

    if result["body_length"] > LONG_EMAIL_WARNING_THRESHOLD:
        result["warnings"] = [
            f"Email body is {result['body_length']} characters; inspect {result['body_saved_to']} "
            "and grep/crop/filter before pasting snippets to avoid overflowing context."
        ]

    return result


def send_email(config: Config, *, to: list[str], subject: str, body: str, cc: list[str] | None = None, attachments: list[str] | None = None) -> dict[str, str]:
    service = api.gmail_service(config)
    raw = _build_mime_message(to, subject, body, cc=cc, attachments=attachments)
    result = api.retry(lambda: service.users().messages().send(userId="me", body={"raw": raw}).execute())
    return {"status": "sent", "id": result.get("id", "")}


def create_draft(config: Config, *, to: list[str], subject: str, body: str, cc: list[str] | None = None, attachments: list[str] | None = None) -> dict[str, Any]:
    service = api.gmail_service(config)
    raw = _build_mime_message(to, subject, body, cc=cc, attachments=attachments)
    result = api.retry(lambda: service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute())
    return {"status": "draft_created", "id": result.get("id", ""), "message_id": result.get("message", {}).get("id", "")}


def reply_to_email(config: Config, *, message_id: str, body: str, attachments: list[str] | None = None, reply_all: bool = False) -> dict[str, str]:
    service = api.gmail_service(config)
    original = api.retry(lambda: service.users().messages().get(userId="me", id=message_id, format="metadata", metadataHeaders=["Subject", "From", "To", "Cc", "Message-ID", "References", "In-Reply-To"]).execute())
    headers = original.get("payload", {}).get("headers", [])
    thread_id = original.get("threadId")

    subject = _get_header(headers, "Subject")
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    from_addr = _get_header(headers, "From")
    to_addrs = [from_addr]
    if reply_all:
        to_header = _get_header(headers, "To")
        cc_header = _get_header(headers, "Cc")
        if to_header:
            to_addrs.extend([a.strip() for a in to_header.split(",") if a.strip()])
        cc = [a.strip() for a in cc_header.split(",") if a.strip()] if cc_header else None
    else:
        cc = None

    msg = _build_mime_body(body, attachments)
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = ", ".join(cc)

    message_id_header = _get_header(headers, "Message-ID")
    references = _get_header(headers, "References")
    if message_id_header:
        msg["In-Reply-To"] = message_id_header
        msg["References"] = f"{references} {message_id_header}".strip() if references else message_id_header

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    send_body: dict[str, Any] = {"raw": raw}
    if thread_id:
        send_body["threadId"] = thread_id

    result = api.retry(lambda: service.users().messages().send(userId="me", body=send_body).execute())
    return {"status": "sent", "id": result.get("id", "")}


def get_attachment(config: Config, *, email_id: str, attachment_id: str, save_path: str) -> dict[str, Any]:
    service = api.gmail_service(config)
    result = api.retry(lambda: service.users().messages().attachments().get(userId="me", messageId=email_id, id=attachment_id).execute())

    data = base64.urlsafe_b64decode(result["data"])
    path = pl.Path(save_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    return {"size": result.get("size", len(data)), "saved_to": str(path)}


def search_emails(config: Config, *, query: str, limit: int = 10, label: str | None = None) -> list[dict[str, Any]]:
    service = api.gmail_service(config)
    kwargs: dict[str, Any] = {"userId": "me", "q": query, "maxResults": min(limit, 100)}
    if label:
        kwargs["labelIds"] = [label]

    results = api.retry(lambda: service.users().messages().list(**kwargs).execute())
    messages = results.get("messages", [])

    output = []
    for msg_ref in messages[:limit]:
        msg = api.retry(lambda mid=msg_ref["id"]: service.users().messages().get(userId="me", id=mid, format="metadata", metadataHeaders=["Subject", "From", "To", "Date"]).execute())
        output.append(_parse_message_snapshot(msg))
    return output


def update_email(config: Config, *, message_id: str, add_labels: list[str] | None = None, remove_labels: list[str] | None = None) -> dict[str, Any]:
    if not add_labels and not remove_labels:
        raise ValueError("Must specify at least --add-labels or --remove-labels")

    service = api.gmail_service(config)
    body: dict[str, Any] = {}
    if add_labels:
        body["addLabelIds"] = add_labels
    if remove_labels:
        body["removeLabelIds"] = remove_labels

    result = api.retry(lambda: service.users().messages().modify(userId="me", id=message_id, body=body).execute())
    return {"status": "updated", "id": result.get("id", ""), "labelIds": result.get("labelIds", [])}
