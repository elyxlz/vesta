---
name: agentmail
description: Send and receive email as the agent via AgentMail (a managed inbox-per-agent service with a free tier). Use when the user mentions "email", "send email", "agent inbox", or wants email without a custom domain. The agent's address is `${username}@agentmail.to`. Inbound mail arrives as a notification with `source=agentmail`. Setup is fully autonomous (no domain, no DNS, no user input on the happy path).
---

# agentmail

Managed agent inbox via [AgentMail](https://agentmail.to). The free tier covers
3 inboxes, 3,000 sends/month (100/day), and webhook-based inbound delivery.
Unlike `cloudflare-email`, there's no domain, DNS, or paid tier required for
basic send + receive.

The agent's address is `${username}@agentmail.to` (default username is the
lowercased agent name).

**Setup**: see [SETUP.md](SETUP.md). Fully autonomous on the happy path:
setup creates a disposable mail.tm inbox, uses it to receive AgentMail's
sign-up OTP, then discards it. No user input required.

## Quick reference

```bash
agentmail setup                                  # one-time signup + inbox + webhook
agentmail send --to <addr> --subject <s> --body <b>
agentmail send --to <addr> --subject <s> --body-file body.txt --html-file body.html
agentmail send --to <addr> --subject <s> --body <b> --in-reply-to <message_id>
agentmail status                                 # show address, inbox id, last inbound
agentmail teardown                               # delete inbox + clear config
```

## Sending email

- Outbound goes through `POST https://api.agentmail.to/inboxes/{id}/messages/send`.
- Free tier: 3,000/mo, 100/day. The CLI surfaces AgentMail's error body if
  you hit a quota or validation problem.
- Pass both `--body` (plain text) and `--html-file` (HTML) when you can -
  text-only sends score worse on spam filters; HTML-only breaks for clients
  that strip HTML.
- To reply on the same thread, pass `--in-reply-to <message_id>` using the
  `message_id` from the inbound notification. The CLI maps it to In-Reply-To
  + References per RFC 5322.

## Receiving email

- AgentMail POSTs each inbound message to a webhook. setup registers a
  webhook URL pointing at the local `agentmail` service through the public
  vestad tunnel, authenticated with a shared `AGENTMAIL_WEBHOOK_SECRET`.
- The local service writes a JSON file to `~/agent/notifications/`. The
  agent's notification loop picks it up like any other source.

## Notification shape

```json
{
  "source": "agentmail",
  "type": "message",
  "message_id": "<rfc822-id>",
  "from": "sender@example.com",
  "to": "athena@agentmail.to",
  "subject": "...",
  "body_text": "...",
  "body_html": "...",
  "in_reply_to": "<parent-rfc822-id>",
  "references": "<root-id> <parent-id>",
  "thread_id": "thr_...",
  "labels": [],
  "received_at": "2026-04-27T11:00:00Z"
}
```

## Configuration storage

| What | Where |
|---|---|
| API key | env var `AGENTMAIL_API_KEY`, persisted to `~/.bashrc` by setup |
| Webhook secret | env var `AGENTMAIL_WEBHOOK_SECRET`, persisted to `~/.bashrc` by setup |
| Inbox id, email address, organization id | `~/.agentmail/config.json` (written by setup) |

`~/.bashrc` is sourced by the agent process on container start, so secrets
persist across restarts without any host-side mechanism.

## When to use this vs cloudflare-email

| Need | Pick |
|---|---|
| Free outbound + inbound, no domain | `agentmail` |
| Vanity address on a domain you own | `cloudflare-email` |
| You want to keep CF Email Routing for inbound (free) on a paid CF Workers plan | `cloudflare-email` |
| You don't have a Cloudflare account or any domain | `agentmail` |

The two skills are independent and can coexist on the same agent; each
inbound notification is tagged with its `source` so handlers can route.

## Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| `setup` times out polling the disposable inbox | AgentMail's anti-fraud rejected the disposable domain (no OTP delivered), or mail.tm is down | Run `agentmail setup --prompt` to do it manually with your own email, or use the browser fallback below |
| `setup` fails at the verify step | Wrong OTP extracted from email, or OTP expired | Re-run `agentmail setup` for a fresh disposable inbox + new OTP |
| `send` fails with HTTP 401 | API key missing or rotated | Re-run `agentmail setup` (will detect the missing key) |
| `send` fails with HTTP 429 | Hit the daily 100-send cap on free tier | Wait, or upgrade to AgentMail's paid plan |
| Inbound never arrives | Webhook can't reach the local service | Check `agentmail status` shows `webhook_url`; confirm the local service is running with `screen -ls`; confirm vestad's public tunnel is up |

## Manual / browser fallbacks

The autonomous flow can fail if AgentMail block-lists the disposable email
domain or mail.tm is down. Two recovery paths:

**`agentmail setup --prompt`** (manual)

Asks for your email and the OTP you receive. No disposable inbox.

**Browser sign-up + `--skip-signup`** (most resilient)

Use the `browser` skill to sign up at https://console.agentmail.to/signup,
generate an API key from the dashboard, then:

```bash
export AGENTMAIL_API_KEY=<paste-key>
agentmail setup --skip-signup
```

`--skip-signup` reuses the env-set key and only does inbox creation + webhook
registration.
