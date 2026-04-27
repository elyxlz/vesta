---
name: cloudflare-email
description: Send and receive email as the agent via Cloudflare Email Service. Use when the user mentions "email", "send email", "reply to that email", "subscribe to a newsletter", or wants the agent to act on inbound mail. The agent's address is `${AGENT_NAME}@${CF_EMAIL_DOMAIN}` (e.g. `athena@vesta.run`). Inbound mail arrives as a notification with `source=cloudflare-email`. Requires one-time setup; see SETUP.md.
---

# cloudflare-email

Send and receive email as the agent. Outbound goes through the Email Sending
REST API; inbound arrives via a Cloudflare Worker that posts each parsed
message to a local FastAPI service, which writes a notification JSON the
agent's notification loop picks up natively (same pattern as whatsapp /
telegram).

The address is `${AGENT_NAME}@${CF_EMAIL_DOMAIN}` (lowercased), e.g.
`athena@vesta.run`.

**Setup**: see [SETUP.md](SETUP.md). One-time, ~10 minutes, requires a
Cloudflare account with a domain on it and an API token.

## Quick reference

```bash
cloudflare-email setup                                      # one-time interactive setup
cloudflare-email reconcile                                  # re-apply routing + secret after token rotation
cloudflare-email send --to <addr> --subject <s> --body <b>
cloudflare-email send --to <addr> --subject <s> --body-file body.txt --html-file body.html
cloudflare-email send --to <addr> --subject <s> --body <b> --in-reply-to <message_id>
cloudflare-email subscribe --url <newsletter-signup-url>    # signs up using a sub-address
cloudflare-email status                                     # show config + last inbound
cloudflare-email teardown                                   # remove routing rules + worker
```

## Sending email

- Outbound goes through `POST /accounts/{account_id}/email/sending/send`
  (no Workers binding; the agent runs in a container, not a Worker).
- The domain must be onboarded for sending. `setup` runs
  `wrangler email sending enable <domain>` for you. After onboarding, DNS
  (SPF + DKIM) propagation can take 5-15 min before sends succeed.
- Pass both `--body` (plain text) and `--html-file` (HTML) when you can.
  Text-only sends score worse on spam filters; HTML-only breaks for clients
  that strip HTML.
- To reply on the same thread, pass `--in-reply-to <message_id>` using the
  `message_id` from the inbound notification. The CLI sets `In-Reply-To`
  and `References` headers per RFC 5322. (This is distinct from CF's
  `reply_to` REST field, which sets the Reply-To envelope address; we
  don't expose that.)

### Reply-on-thread example

Inbound notification:

```json
{ "source": "cloudflare-email", "message_id": "<x123@example.com>",
  "from": "alice@example.com", "subject": "Lunch?" }
```

Reply on the same thread:

```bash
cloudflare-email send \
  --to alice@example.com \
  --subject "Re: Lunch?" \
  --body "Tomorrow at 1pm works." \
  --in-reply-to "<x123@example.com>"
```

## Receiving email

- A Cloudflare Worker (in `worker/`) parses inbound MIME with `postal-mime`
  and POSTs the result to the local `cloudflare-email` service over the
  public vestad tunnel, authenticated with a shared `WORKER_SECRET`.
- The service writes a JSON file to `~/agent/notifications/`. The agent's
  notification loop picks it up like any other source.
- Sub-addressing works automatically: `${local}+<tag>@${domain}` routes to
  the same agent. Use sub-addresses to namespace inbound:

| Use case | Address pattern |
|---|---|
| Direct mail from a human | `athena@vesta.run` |
| Newsletter signups | `athena+<source>@vesta.run` |
| Account verification flows | `athena+verify-<service>@vesta.run` |

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
  "in_reply_to": "<parent-rfc822-id>",
  "references": "<root-id> <parent-id>",
  "headers": {"...": "..."},
  "received_at": "2026-04-27T11:00:00Z"
}
```

## Newsletter subscriptions

`cloudflare-email subscribe --url <signup>` POSTs the agent's sub-address
(`${local}+<host-slug>@${domain}`) to the signup form, then watches the
inbox for ~5 min for a confirmation email and visits any
`confirm|verify|activate|subscribe` link it finds. Best-effort: providers
that require JavaScript or bot challenges will fail; in that case the
confirmation email still lands as a normal notification, so the user
(or agent) can click the link manually.

The subscription is logged to `~/.cloudflare-email/subscriptions.json`
(signup URL, sub-address, timestamp). There is no `unsubscribe` command
yet; to stop a feed, click the unsubscribe link in any inbound message
or delete the routing rule for that sub-address.

## Configuration storage

| What | Where |
|---|---|
| API token | env var `CF_API_TOKEN`, persisted to `~/.bashrc` by setup |
| Worker secret | env var `CF_WORKER_SECRET`, persisted to `~/.bashrc` by setup |
| Domain, address, zone/account IDs, worker name | `~/.cloudflare-email/config.json` (written by setup) |
| `CF_EMAIL_DOMAIN`, `CF_EMAIL_ADDRESS` | `~/.bashrc` for shell convenience (config.json is the source of truth) |

`~/.bashrc` is sourced by the agent process on container start, so secrets
persist across restarts without any host-side mechanism. Rotate by editing
`~/.bashrc` (or by re-running `cloudflare-email setup`, which prompts again
when `CF_API_TOKEN` is missing).

## Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| `send` fails with "sender domain not verified" | DNS hasn't propagated after `wrangler email sending enable`, or `enable` was never run | Run `wrangler email sending dns get <domain>`, verify SPF + DKIM records exist, wait 5-15 min |
| `send` fails with HTTP 400 on `from` | Using Workers-binding field shape (`{email: ...}`) | The CLI uses the REST shape (`{address: ...}`) - should be automatic; if you've patched it, revert |
| Reply doesn't thread on the recipient's side | `--in-reply-to` not passed | Pass the inbound `message_id` verbatim (with angle brackets) as `--in-reply-to` |
| Inbound never arrives | Worker can't reach the local service | Check `cloudflare-email status` shows `vestad_tunnel`; check `screen -ls` shows the `cloudflare-email` session; check the service was registered with `"public": true` |
| `subscribe` returns "no confirmation email seen" | Provider requires JS / bot-protection | Click the confirmation link from the inbound notification manually |
