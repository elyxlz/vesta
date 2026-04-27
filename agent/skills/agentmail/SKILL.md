---
name: agentmail
description: Send and receive email as the agent via AgentMail (managed inbox-per-agent service with a free tier). Use when the user mentions "email", "send email", "agent inbox", or wants email without a custom domain. The agent's address is `${username}@agentmail.to`. Inbound mail arrives as a notification with `source=agentmail`. Setup is fully autonomous; no domain, no DNS, no user input on the happy path.
---

# agentmail

Managed agent inbox via [AgentMail](https://agentmail.to). Free tier: 3
inboxes per account, 3,000 sends/month (100/day), webhook-based inbound
delivery. No domain, no DNS, no paid plan required for basic send + receive.

The agent's address is `${username}@agentmail.to`, where `username`
defaults to the lowercased agent name.

**Setup**: see [SETUP.md](SETUP.md). Autonomous on the happy path: setup
creates a disposable mail.tm inbox to relay AgentMail's sign-up OTP, then
discards it. Verified end-to-end against live APIs.

## Quick reference

```bash
agentmail setup                                              # autonomous (default)
agentmail setup --prompt                                     # manual: ask for email + OTP
agentmail setup --skip-signup                                # use AGENTMAIL_API_KEY from env
agentmail send --to <addr> --subject <s> --body <b>
agentmail send --to <addr> --subject <s> --body-file body.txt --html-file body.html
agentmail send --to <addr> --subject <s> --body <b> --in-reply-to <message_id>
agentmail status                                             # show address, inbox id, last inbound
agentmail teardown                                           # delete inbox + clear config
```

## Sending email

- Outbound: `POST https://api.agentmail.to/v0/inboxes/{inbox_id}/messages/send`
  authenticated with `Bearer $AGENTMAIL_API_KEY`.
- Free tier caps: 3,000/month, 100/day. The CLI surfaces AgentMail's error
  body verbatim if you hit a quota or validation problem.
- Pass both `--body` (plain text) and `--html-file` (HTML) when you can.
  Text-only sends score worse on spam filters; HTML-only breaks for clients
  that strip HTML.
- To reply on the same thread, pass `--in-reply-to <message_id>` using the
  `message_id` from the inbound notification verbatim (with angle brackets).
  The CLI sets `In-Reply-To` and `References` headers per RFC 5322. (This is
  distinct from CF's `reply_to` REST field, which sets the Reply-To envelope
  address; we don't expose that.)

### Reply-on-thread example

Inbound notification:

```json
{ "source": "agentmail", "message_id": "<abc@email.amazonses.com>",
  "from": "alice@example.com", "subject": "Lunch?" }
```

Reply on the same thread:

```bash
agentmail send \
  --to alice@example.com \
  --subject "Re: Lunch?" \
  --body "Tomorrow at 1pm works." \
  --in-reply-to "<abc@email.amazonses.com>"
```

## Receiving email

AgentMail POSTs each inbound message to a webhook at
`${VESTAD_TUNNEL}/agents/${AGENT_NAME}/agentmail/webhook?secret=…`. The
local FastAPI service (`agentmail serve`) verifies the secret, writes a
JSON file to `~/agent/notifications/`, and the agent's notification loop
picks it up like any other source.

## Notification shape

```json
{
  "source": "agentmail",
  "type": "message",
  "message_id": "<...@email.amazonses.com>",
  "from": "sender@example.com",
  "to": "athena@agentmail.to",
  "subject": "...",
  "body_text": "...",
  "body_html": "...",
  "in_reply_to": "<parent-id@email.amazonses.com>",
  "references": "<root-id> <parent-id>",
  "thread_id": "2719807e-deeb-4edb-b65b-c52e250e6c1a",
  "labels": [],
  "received_at": "2026-04-27T11:00:00Z"
}
```

## Configuration storage

| What | Where |
|---|---|
| API key | env var `AGENTMAIL_API_KEY`, persisted to `~/.bashrc` |
| Webhook secret | env var `AGENTMAIL_WEBHOOK_SECRET`, persisted to `~/.bashrc` |
| Inbox id, address, organization id | `~/.agentmail/config.json` |

`~/.bashrc` is sourced by the agent process on container start, so secrets
persist across restarts without any host-side mechanism.

## When to use this vs cloudflare-email

| Need | Pick |
|---|---|
| Free outbound + inbound, no domain | `agentmail` |
| Vanity address on a domain you own | `cloudflare-email` |
| You're already on Cloudflare Workers Paid for routing | `cloudflare-email` |
| You don't have a Cloudflare account or any domain | `agentmail` |

The two skills are independent and can coexist on the same agent; each
inbound notification is tagged with its `source` so handlers can route.

## Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| `setup` times out at the OTP poll step (3 min) | AgentMail's anti-fraud rejected the disposable domain (sign-up succeeded but no OTP delivered), or mail.tm is down | Run `agentmail setup --prompt` and provide your own email; or sign up at https://console.agentmail.to via the `browser` skill, then `export AGENTMAIL_API_KEY=<key> && agentmail setup --skip-signup` |
| `setup` fails at `verify` with HTTP 401 | OTP wrong (regex pulled a non-OTP number from the email) or expired (~10 min window) | Re-run `agentmail setup` for a fresh disposable inbox + new OTP |
| `send` fails with HTTP 401 | `AGENTMAIL_API_KEY` missing or rotated | Re-run `agentmail setup` (if missing) or `source ~/.bashrc` (if just rotated) |
| `send` fails with HTTP 429 | Hit the 100/day or 3,000/month free-tier cap | Wait, or upgrade AgentMail to a paid plan |
| Inbound never arrives | Webhook can't reach the local service | `agentmail status` should show `webhook_url`; `screen -ls` should show the `agentmail` session; the service must have been registered with `"public": true` |
