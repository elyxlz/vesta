---
name: agentmail
description: Send and receive email as the agent via AgentMail (managed inbox-per-agent service with a free tier). Use when the user mentions "email", "send email", "agent inbox", or wants email without a custom domain. The agent's address is `${username}@agentmail.to`. Inbound mail arrives as a notification with `source=agentmail`. Setup is fully autonomous; no domain, no DNS, no user input on the happy path. The skill wraps the official `agentmail` CLI so all upstream commands work transparently.
---

# agentmail

Vesta-side bridge to [AgentMail](https://agentmail.to). Free tier: 3 inboxes,
3,000 sends/month (100/day), webhook-based inbound. No domain, no DNS, no
paid plan required.

The agent's address is `${username}@agentmail.to`, where `username`
defaults to the lowercased agent name.

## How this skill is structured

The `agentmail` binary is a thin Python wrapper. Four verbs are
Vesta-specific:

- `agentmail setup` - autonomous AgentMail account + inbox + webhook
  provisioning, plus a local install of the official CLI for passthrough.
- `agentmail serve` - local FastAPI receiver for AgentMail webhooks; writes
  notifications to `~/agent/notifications/`.
- `agentmail status` - show the configured address, inbox id, webhook URL,
  and last inbound notification.
- `agentmail teardown` - delete the inbox + webhook + clear local config.

**Anything else is passed through to the official `agentmail` CLI**
(installed locally to `~/.agentmail/node_modules/.bin/` by setup). The
agent only sees one binary on PATH.

## Quick reference

```bash
# Vesta verbs
agentmail setup                                                  # autonomous (default)
agentmail setup --prompt                                         # manual: ask for email + OTP
agentmail setup --skip-signup                                    # use AGENTMAIL_API_KEY from env
agentmail status
agentmail teardown

# Passthrough to the official CLI (full reference: https://docs.agentmail.to/integrations/cli)
agentmail inboxes:messages send --inbox-id <id> --to <addr> --subject <s> --text <t>
agentmail inboxes:messages reply --inbox-id <id> --message-id <id> --text <t>
agentmail inboxes:threads list --inbox-id <id>
agentmail inboxes:messages list --inbox-id <id>
agentmail webhooks list
agentmail --help                                                 # both Vesta verbs and passthrough help
```

The `--inbox-id` is in `agentmail status` (key `inbox_id`).

## Sending email

Use the upstream verb:

```bash
agentmail inboxes:messages send \
  --inbox-id "$(agentmail status | jq -r .inbox_id)" \
  --to recipient@example.com \
  --subject "Hello" \
  --text "Plain body" \
  --html "<p>HTML body</p>"
```

Free tier caps: 3,000/month, 100/day. The CLI surfaces AgentMail's error
body verbatim on failure. Pass both `--text` and `--html` when you can -
text-only sends score worse on spam filters; HTML-only breaks for clients
that strip HTML.

To reply on the same thread, use `inboxes:messages reply` (the upstream
CLI sets `In-Reply-To` and `References` correctly):

```bash
agentmail inboxes:messages reply \
  --inbox-id <inbox_id> \
  --message-id "<inbound-message-id>" \
  --text "Tomorrow at 1pm works."
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
| Inbox id, address, webhook id, username | `~/.agentmail/config.json` |
| Official npm CLI | `~/.agentmail/node_modules/.bin/agentmail` |

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
| `agentmail inboxes:messages send` fails with "official AgentMail CLI not installed" | Setup hadn't run, or its npm install step failed | Re-run `agentmail setup`; check the npm install log |
| Send fails with HTTP 401 | `AGENTMAIL_API_KEY` missing or rotated | Re-run `agentmail setup` (if missing) or `source ~/.bashrc` (if just rotated) |
| Send fails with HTTP 429 | Hit the 100/day or 3,000/month free-tier cap | Wait, or upgrade AgentMail to a paid plan |
| Inbound never arrives | Webhook can't reach the local service | `agentmail status` should show `webhook_url`; `screen -ls` should show the `agentmail` session; the service must have been registered with `"public": true` |
| Send fails with `string was used where mapping is expected` on `--headers` | `--headers` value contains an angle-bracketed Message-Id (e.g. `In-Reply-To=<msg-id>`); the upstream CLI parses the leading `<` as a YAML flow-style list opener | Use `inboxes:messages reply --message-id "<parent-id>"` to thread replies -- the CLI sets `In-Reply-To` and `References` server-side. Upstream bug in `agentmail-cli` |
| Send fails with `Invalid input: expected string, received object` on `subject` | `--subject` value contains `": "` (colon followed by space), which the upstream CLI parses as a YAML mapping | Drop the space (`Re:topic`), rephrase to avoid `": "`, or use `inboxes:messages reply` which derives the subject from the parent and sidesteps the issue. Upstream bug in `agentmail-cli` |
