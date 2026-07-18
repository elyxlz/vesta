import base64
import pathlib as pl
import re
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html.parser import HTMLParser
from typing import Any

from . import api
from .config import Config

EMAIL_SAVE_SUBDIR = "emails"
LONG_EMAIL_WARNING_THRESHOLD = 5000

# Block-level tags that should force a line break when flattening HTML to text.
_HTML_BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "tr",
    "li",
    "ul",
    "ol",
    "table",
    "thead",
    "tbody",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "section",
    "article",
    "header",
    "footer",
    "hr",
    "pre",
}


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
    # Deterministic filename keyed on the message id: re-fetching the same message
    # OVERWRITES its file instead of accumulating a new timestamped copy each call.
    subject_fragment = _sanitize_filename(subject or "")
    id_fragment = _sanitize_filename(message_id)[:32]
    filename = f"{subject_fragment[:40]}_{id_fragment}.txt".strip("_")
    return base_dir / filename


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _parse_message_snapshot(msg: dict) -> dict:
    payload = msg["payload"] if "payload" in msg else {}
    headers = payload["headers"] if "headers" in payload else []
    return {
        "id": msg["id"],
        "threadId": msg["threadId"] if "threadId" in msg else None,
        "subject": _get_header(headers, "Subject"),
        "from": _get_header(headers, "From"),
        "to": _get_header(headers, "To"),
        "date": _get_header(headers, "Date"),
        "snippet": msg["snippet"] if "snippet" in msg else "",
        "labelIds": msg["labelIds"] if "labelIds" in msg else [],
    }


class _HTMLToText(HTMLParser):
    """Flatten HTML to readable text while PRESERVING link targets.

    Anchor text keeps its visible label and, when the ``href`` is a real URL not
    already spelled out in the text, appends `` (href)`` so the destination
    survives. ``<script>``/``<style>`` bodies are dropped; block tags become line
    breaks. Entities are converted by HTMLParser (convert_charrefs defaults on).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._href: str | None = None
        self._anchor_start = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor_start = len(self.parts)
        elif tag in _HTML_BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "a":
            href = self._href
            self._href = None
            if href and not href.startswith(("#", "javascript:", "mailto:")):
                anchor_text = "".join(self.parts[self._anchor_start :])
                if href not in anchor_text:
                    self.parts.append(f" ({href})")
        elif tag in _HTML_BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)

    def get_text(self) -> str:
        text = "".join(self.parts)
        # Collapse runs of spaces/tabs, trim each line, cap blank-line runs at one.
        text = re.sub(r"[ \t]+", " ", text)
        text = "\n".join(line.strip() for line in text.split("\n"))
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _html_to_text(html: str) -> str:
    parser = _HTMLToText()
    parser.feed(html)
    parser.close()
    return parser.get_text()


def _decode_body_data(body: dict) -> str:
    data = body.get("data") if isinstance(body, dict) else None
    if not data:
        return ""
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")


def _collect_body_parts(payload: dict, plain: list[str], html: list[str]) -> None:
    """Walk the MIME tree, gathering text/plain and text/html leaves separately.

    Handles arbitrarily nested multipart/alternative and multipart/mixed. Skips
    parts with a filename (attachments/inline images), which are not body text.
    """
    parts = payload.get("parts")
    if parts:
        for part in parts:
            _collect_body_parts(part, plain, html)
        return
    if payload.get("filename"):
        return
    mime = payload.get("mimeType") or ""
    if mime == "text/plain":
        plain.append(_decode_body_data(payload.get("body", {})))
    elif mime == "text/html":
        html.append(_decode_body_data(payload.get("body", {})))


def _get_body_text(payload: dict) -> str:
    """Best readable body: prefer text/plain, else text/html flattened with links."""
    plain: list[str] = []
    html: list[str] = []
    _collect_body_parts(payload, plain, html)

    plain_text = "\n".join(t for t in plain if t).strip()
    if plain_text:
        return plain_text

    html_joined = "\n".join(t for t in html if t)
    if html_joined.strip():
        return _html_to_text(html_joined)
    return ""


def _get_attachments_info(payload: dict) -> list[dict]:
    attachments = []
    for part in payload["parts"] if "parts" in payload else []:
        part_body = part["body"] if "body" in part else {}
        if (part.get("filename")) and ("attachmentId" in part_body):
            attachments.append(
                {
                    "id": part_body["attachmentId"],
                    "name": part["filename"],
                    "size": part_body["size"] if "size" in part_body else 0,
                    "mimeType": part["mimeType"] if "mimeType" in part else "application/octet-stream",
                }
            )
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


def _fetch_message_snapshots(service, msg_refs: list[dict], limit: int) -> list[dict[str, Any]]:
    output = []
    for msg_ref in msg_refs[:limit]:
        msg = api.retry(
            lambda mid=msg_ref["id"]: (
                service.users()
                .messages()
                .get(userId="me", id=mid, format="metadata", metadataHeaders=["Subject", "From", "To", "Date"])
                .execute()
            )
        )
        output.append(_parse_message_snapshot(msg))
    return output


def list_emails(config: Config, *, label: str = "INBOX", limit: int = 10) -> list[dict[str, Any]]:
    service = api.gmail_service(config)
    results = api.retry(lambda: service.users().messages().list(userId="me", labelIds=[label], maxResults=min(limit, 100)).execute())
    messages = results["messages"] if "messages" in results else []
    return _fetch_message_snapshots(service, messages, limit)


def get_email(config: Config, *, message_id: str, include_attachments: bool = True, save_to_file: str | None = None) -> dict[str, Any]:
    service = api.gmail_service(config)
    msg = api.retry(lambda: service.users().messages().get(userId="me", id=message_id, format="full").execute())
    payload = msg["payload"] if "payload" in msg else {}
    headers = payload["headers"] if "headers" in payload else []

    subject = _get_header(headers, "Subject")
    full_body = _get_body_text(payload)

    result: dict[str, Any] = {
        "id": msg["id"],
        "threadId": msg["threadId"] if "threadId" in msg else None,
        "subject": subject,
        "from": _get_header(headers, "From"),
        "to": _get_header(headers, "To"),
        "cc": _get_header(headers, "Cc"),
        "date": _get_header(headers, "Date"),
        "snippet": msg["snippet"] if "snippet" in msg else "",
        "labelIds": msg["labelIds"] if "labelIds" in msg else [],
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


def send_email(
    config: Config, *, to: list[str], subject: str, body: str, cc: list[str] | None = None, attachments: list[str] | None = None
) -> dict[str, str]:
    service = api.gmail_service(config)
    raw = _build_mime_message(to, subject, body, cc=cc, attachments=attachments)
    result = api.retry(lambda: service.users().messages().send(userId="me", body={"raw": raw}).execute())
    return {"status": "sent", "id": result["id"] if "id" in result else ""}


def create_draft(
    config: Config, *, to: list[str], subject: str, body: str, cc: list[str] | None = None, attachments: list[str] | None = None
) -> dict[str, Any]:
    service = api.gmail_service(config)
    raw = _build_mime_message(to, subject, body, cc=cc, attachments=attachments)
    result = api.retry(lambda: service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute())
    result_msg = result["message"] if "message" in result else {}
    return {
        "status": "draft_created",
        "id": result["id"] if "id" in result else "",
        "message_id": result_msg["id"] if "id" in result_msg else "",
    }


def reply_to_email(
    config: Config, *, message_id: str, body: str, attachments: list[str] | None = None, reply_all: bool = False
) -> dict[str, str]:
    service = api.gmail_service(config)
    original = api.retry(
        lambda: (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["Subject", "From", "To", "Cc", "Message-ID", "References", "In-Reply-To"],
            )
            .execute()
        )
    )
    orig_payload = original["payload"] if "payload" in original else {}
    headers = orig_payload["headers"] if "headers" in orig_payload else []
    thread_id = original["threadId"] if "threadId" in original else None

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
    return {"status": "sent", "id": result["id"] if "id" in result else ""}


def get_attachment(config: Config, *, email_id: str, attachment_id: str, save_path: str) -> dict[str, Any]:
    service = api.gmail_service(config)
    result = api.retry(lambda: service.users().messages().attachments().get(userId="me", messageId=email_id, id=attachment_id).execute())

    data = base64.urlsafe_b64decode(result["data"])
    path = pl.Path(save_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    return {"size": result["size"] if "size" in result else len(data), "saved_to": str(path)}


def search_emails(config: Config, *, query: str, limit: int = 10, label: str | None = None) -> list[dict[str, Any]]:
    service = api.gmail_service(config)
    kwargs: dict[str, Any] = {"userId": "me", "q": query, "maxResults": min(limit, 100)}
    if label:
        kwargs["labelIds"] = [label]

    results = api.retry(lambda: service.users().messages().list(**kwargs).execute())
    messages = results["messages"] if "messages" in results else []
    return _fetch_message_snapshots(service, messages, limit)


def update_email(
    config: Config, *, message_id: str, add_labels: list[str] | None = None, remove_labels: list[str] | None = None
) -> dict[str, Any]:
    if not add_labels and not remove_labels:
        raise ValueError("Must specify at least --add-labels or --remove-labels")

    service = api.gmail_service(config)
    body: dict[str, Any] = {}
    if add_labels:
        body["addLabelIds"] = add_labels
    if remove_labels:
        body["removeLabelIds"] = remove_labels

    result = api.retry(lambda: service.users().messages().modify(userId="me", id=message_id, body=body).execute())
    return {"status": "updated", "id": result["id"] if "id" in result else "", "labelIds": result["labelIds"] if "labelIds" in result else []}
