---
name: cloudflare-email
description: Use this skill when the user asks about "email", "send email", "subscribe to newsletter", or needs the agent to send/receive email via Cloudflare Email Service. The agent's address is `${AGENT_NAME}@${CF_EMAIL_DOMAIN}` (e.g. athena@vesta.run). Inbound email lands as a notification with `source=cloudflare-email`. Requires a one-time setup, see SETUP.md.
---

# cloudflare-email

Email send/receive for the agent via Cloudflare Email Service. The address is
`${AGENT_NAME}@${CF_EMAIL_DOMAIN}`. Inbound email arrives as a notification, the
agent replies with the `cloudflare-email` CLI on the same channel.

**Setup**: See [SETUP.md](SETUP.md). One-time, requires a Cloudflare account with
a domain on the account and an API token.

## Quick reference

```bash
cloudflare-email setup                              # interactive: creates routing rule + deploys worker
cloudflare-email send --to <addr> --subject <s> --body <b>
cloudflare-email send --to <addr> --subject <s> --body-file /path/to/body.txt
cloudflare-email send --to <addr> --subject <s> --body <b> --reply-to <msgid>
cloudflare-email subscribe --url <newsletter-signup-url>   # signs up and watches inbox for confirmation link
cloudflare-email status                             # shows configured domain, address, last inbound
```

## Notes

- Address: `${AGENT_NAME}@${CF_EMAIL_DOMAIN}`. Default domain is `vesta.run`, set via
  env `CF_EMAIL_DOMAIN` in `~/.bashrc`. Agent name comes from `$AGENT_NAME`.
- Sub-addressing works: `athena+newsletters@vesta.run`, `athena+research@vesta.run`,
  etc. all route to the same agent. Useful for filtering inbound by namespace.
- Outbound goes through the Cloudflare Email Send API. SPF/DKIM/DMARC are
  auto-configured at routing-rule creation time.
- Inbound is handled by a Cloudflare Worker (`worker/`) that POSTs to the local
  service. Service writes to `~/agent/notifications/` so the agent picks it up
  natively, same shape as whatsapp/telegram messages.
- Auth: API token stored in keeper as `cloudflare/api-token`. Worker secret stored
  in keeper as `cloudflare-email/worker-secret`. Domain stored in `~/.bashrc` as
  `CF_EMAIL_DOMAIN`.

## Notification shape

```json
{
  "source": "cloudflare-email",
  "type": "message",
  "message_id": "<rfc822-id>",
  "from": "sender@example.com",
  "to": "athena+ns@vesta.run",
  "subject": "...",
  "body_text": "...",
  "body_html": "...",
  "received_at": "2026-04-27T11:00:00Z"
}
```

## Newsletter subscriptions

`cloudflare-email subscribe --url <signup>` signs up using the agent's address,
then watches for the confirmation email and clicks the link automatically. Logs
the subscription source so the agent can unsubscribe later if the noise outweighs
the value.

## When to use a sub-address

- Mo (or any human contact) emails the bare agent address: `athena@vesta.run`
- Newsletter signups: `athena+<source>@vesta.run` so noise is sortable
- Account verification flows: `athena+verify-<service>@vesta.run`

## Known limitations during CF beta

- No IMAP/POP3 retrieval. All inbound goes via the Worker.
- The Worker has a 30s execution limit per email. Long-form processing should
  push the body to a queue (D1 or R2) and process async.
