#!/usr/bin/env python3
"""Create a threaded reply(-all) DRAFT in Outlook, leaving it unsent for the user to review + send.

The microsoft CLI's `email reply` ALWAYS sends and `email draft` orphans the thread (no
conversationId). This fills the gap: createReply/createReplyAll (Graph pre-fills recipients +
quoted history), PATCH the body (our text prepended above the preserved quote), attach files,
and STOP before /send. Idempotent-ish: pass --replace-draft <id> to delete a prior draft first
so repeated edits leave exactly one draft.

Run with the CLI's own venv to avoid uv rebuilding the agent root venv:
  ~/agent/skills/microsoft/cli/.venv/bin/python ~/agent/skills/microsoft/scripts/reply_draft.py \
    --account user@example.com --base-msg-id <ID> --body-file /tmp/body.txt \
    --attach /path/a.pdf [--reply-all] [--replace-draft <old_id>]

Body file is plain text: lines starting "- " become <li> bullets, blank lines become spacing.
Prints the new draft id (last 16 chars + full) so a follow-up edit can pass --replace-draft.
"""

import argparse
import html
import sys

sys.path.insert(0, "/root/agent/skills/microsoft/cli/src")
import httpx
from microsoft_cli import config as cfgmod, auth, graph, email as emailmod


def text_to_html(raw: str) -> str:
    parts: list[str] = []
    in_ul = False
    for ln in raw.rstrip("\n").split("\n"):
        if ln.startswith("- "):
            if not in_ul:
                parts.append("<ul>")
                in_ul = True
            parts.append("<li>" + html.escape(ln[2:]) + "</li>")
        else:
            if in_ul:
                parts.append("</ul>")
                in_ul = False
            parts.append("<br>" if ln.strip() == "" else "<div>" + html.escape(ln) + "</div>")
    if in_ul:
        parts.append("</ul>")
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--base-msg-id", required=True, help="message id to reply to (latest in thread)")
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--attach", action="append", default=[], help="file path; repeatable")
    ap.add_argument("--reply-all", action="store_true")
    ap.add_argument("--replace-draft", default=None, help="delete this draft id first (for re-edits)")
    args = ap.parse_args()

    config = cfgmod.Config()
    client = httpx.Client(timeout=60)
    account_id = auth.get_account_id_by_email(args.account, config.cache_file)

    if args.replace_draft:
        try:
            graph.request_cfg(config, client, "DELETE", f"/me/messages/{args.replace_draft}", account_id)
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup, report and continue
            print(f"warn: could not delete old draft: {exc}", file=sys.stderr)

    endpoint = "createReplyAll" if args.reply_all else "createReply"
    draft = graph.request_cfg(config, client, "POST", f"/me/messages/{args.base_msg_id}/{endpoint}", account_id)
    if not draft or "id" not in draft:
        print("error: failed to create reply draft", file=sys.stderr)
        return 1
    draft_id = draft["id"]

    existing = graph.request_cfg(
        config, client, "GET", f"/me/messages/{draft_id}", account_id, params={"$select": "body,toRecipients,ccRecipients"}
    )
    quoted = existing["body"]["content"]
    to = ", ".join(r["emailAddress"]["address"] for r in existing.get("toRecipients", []))
    cc = ", ".join(r["emailAddress"]["address"] for r in existing.get("ccRecipients", []))

    body_html = text_to_html(open(args.body_file).read())
    graph.request_cfg(
        config,
        client,
        "PATCH",
        f"/me/messages/{draft_id}",
        account_id,
        json={"body": {"contentType": "HTML", "content": body_html + "<br><br>" + quoted}},
    )

    for path in args.attach:
        content_bytes, name, size = emailmod._read_attachment(path)
        if size < emailmod.LARGE_ATTACHMENT_THRESHOLD:
            graph.request_cfg(
                config, client, "POST", f"/me/messages/{draft_id}/attachments", account_id, json=emailmod._file_attachment(name, content_bytes)
            )
        else:
            graph.upload_mail_attachment_cfg(config, client, draft_id, name, content_bytes, account_id)

    chk = graph.request_cfg(
        config,
        client,
        "GET",
        f"/me/messages/{draft_id}",
        account_id,
        params={"$select": "subject,isDraft", "$expand": "attachments($select=name,size)"},
    )
    print(f"draft_id: {draft_id}")
    print(f"subject: {chk['subject']} | isDraft: {chk['isDraft']}")
    print(f"to: {to}")
    print(f"cc: {cc}")
    print(f"attachments: {[a['name'] for a in chk.get('attachments', [])]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
