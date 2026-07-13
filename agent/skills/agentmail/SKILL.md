---
name: agentmail
description: Send and receive email as the agent via AgentMail (managed inbox-per-agent, free tier). Use for "email", "send email", or "agent inbox" without a custom domain; inbound mail arrives as a notification.
---

# agentmail

Vesta-side bridge to [AgentMail](https://agentmail.to). Free tier: 3 inboxes,
3,000 sends/month (100/day), webhook-based inbound. No domain, no DNS, no
paid plan required.

The agent's address is `${username}@agentmail.to`, where `username`
defaults to the lowercased agent name.

## Quick reference

The `agentmail` binary is a thin Python wrapper: the Vesta verbs below are
local, and anything else passes through to the official `agentmail` CLI
(installed to `~/.agentmail/node_modules/.bin/` by setup). One binary on PATH.

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

The CLI surfaces AgentMail's error
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
local FastAPI service (`agentmail serve`) verifies the secret and writes a
JSON file to `~/agent/notifications/`.

## Notification shape

Fields: `source` (`agentmail`), `type`, `from`, `to`, `subject`, `thread_id`,
`in_reply_to`, `message_id`, `body_text`, `body_html`, `references`, `labels`, `received_at`.

## Configuration storage

| What | Where |
|---|---|
| API key | env var `AGENTMAIL_API_KEY`, persisted to `~/.bashrc` |
| Webhook secret | env var `AGENTMAIL_WEBHOOK_SECRET`, persisted to `~/.bashrc` |
| Inbox id, address, webhook id, username | `~/.agentmail/config.json` |
| Official npm CLI | `~/.agentmail/node_modules/.bin/agentmail` |

## When to use this vs cloudflare-email

Pick `agentmail` for free outbound + inbound with no domain or Cloudflare
account; pick `cloudflare-email` for a vanity address on a domain you own (or
if already on Cloudflare Workers Paid for routing). The two are independent and
can coexist; each inbound notification is tagged with its `source` for routing.

## Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| `setup` times out at the OTP poll (3 min) | Anti-fraud rejected the disposable domain, or mail.tm is down | `agentmail setup --prompt` with your own email; or sign up at https://console.agentmail.to via `browser`, then `export AGENTMAIL_API_KEY=<key> && agentmail setup --skip-signup` |
| `setup` fails at `verify` with 401 | OTP wrong or expired (~10 min window) | Re-run `agentmail setup` for a fresh inbox + OTP |
| Send fails: "official AgentMail CLI not installed" | Setup never ran, or its npm install failed | Re-run `agentmail setup`; check the npm install log |
| Send fails with 401 | `AGENTMAIL_API_KEY` missing or rotated | Re-run `agentmail setup`, or `source ~/.bashrc` if just rotated |
| Send fails with 429 | Hit the 100/day or 3,000/month cap | Wait, or upgrade to a paid plan |
| Inbound never arrives | Webhook can't reach the local service | `agentmail status` must show `webhook_url`; `screen -ls` must show the `agentmail` session (registered with `"public": true`) |
| Send fails: `string was used where mapping is expected` on `--headers` | Upstream bug: an angle-bracketed Message-Id (`In-Reply-To=<msg-id>`) makes the CLI read the leading `<` as a YAML list | Use `inboxes:messages reply --message-id "<parent-id>"`; it sets `In-Reply-To`/`References` server-side |
| Send fails: `Invalid input: expected string, received object` on `subject` | Upstream bug: a `": "` in `--subject` is parsed as a YAML mapping | Drop the space (`Re:topic`) or avoid `": "`; or use `inboxes:messages reply`, which derives the subject from the parent |
