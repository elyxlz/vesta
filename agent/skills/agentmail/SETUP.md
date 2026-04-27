# agentmail setup

One-time setup, ~2 minutes. Sign-up is programmatic; you'll need to paste an
OTP from your email once.

## Prerequisites

- An email address you control (any provider) where AgentMail will send the
  OTP for sign-up verification.
- `node` + `npm` not required (no Worker, no DNS).

That's it. No Cloudflare account, no domain, no DNS records, no paid plan.

## 1. Run the setup CLI

```bash
agentmail setup
```

Setup walks through, in order:

1. **Sign-up** (skipped if `AGENTMAIL_API_KEY` is already set):
   - Prompts for `human_email` (where the OTP gets sent) and `username` (your
     agent's local-part; default is `$AGENT_NAME` lowercased).
   - POSTs to `https://api.agentmail.to/agent/sign-up`.
   - Prompts you to paste the OTP (check your email; expires in ~10 min).
   - POSTs to `/agent/verify`. Persists `AGENTMAIL_API_KEY` to `~/.bashrc`.
2. **Inbox creation**: POSTs to `/inboxes` with the chosen username. Stores
   the inbox id and full email address in `~/.agentmail/config.json`.
3. **Webhook registration**: registers `${VESTAD_TUNNEL}/agents/${AGENT_NAME}/agentmail/webhook`
   with AgentMail. Generates a shared `AGENTMAIL_WEBHOOK_SECRET`, persists it
   to `~/.bashrc`, and includes it in the webhook URL as a query param. The
   local service rejects unauthenticated callbacks.

After this, `cloudflare-email status`-equivalent verification:

```bash
agentmail status
```

…should print the inbox id, address, and webhook URL.

## 2. Register and start the local service

The webhook reaches the local FastAPI service through the public vestad
tunnel; that's why the service must be registered with `"public": true`.

```bash
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services \
  -H "X-Agent-Token: $AGENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"agentmail","public":true}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")

screen -dmS agentmail agentmail serve --port $PORT
```

Append the same two-line block to `~/agent/prompts/restart.md` so the
service comes back up after a container restart.

**Verify**: `curl http://127.0.0.1:$PORT/health` should return
`{"ok": true, "address": "<your-address>"}`.

## 3. Send a test email

```bash
agentmail send \
  --to <your-personal-email> \
  --subject "test from $AGENT_NAME" \
  --body "hello"
```

Reply to it from your personal inbox, then watch for the inbound notification:

```bash
ls -la ~/agent/notifications/ | grep agentmail
```

## Skip programmatic sign-up

If you already have an AgentMail account (signed up via console or browser),
grab your API key from `https://console.agentmail.to`, then:

```bash
export AGENTMAIL_API_KEY=<paste-key>
agentmail setup --skip-signup
```

This skips the sign-up + OTP loop and only does inbox creation + webhook
registration.

## Token rotation

Edit `~/.bashrc`, replace the `export AGENTMAIL_API_KEY=...` line with the
new value, then:

```bash
source ~/.bashrc
agentmail status
```

If `status` shows the inbox + webhook still resolve correctly, you're done.
No re-registration needed.

## Uninstall

```bash
agentmail teardown
```

Deletes the inbox via the AgentMail API and clears `~/.agentmail/config.json`.
The AgentMail account itself is left alone (you can have multiple inboxes per
account; deleting the account requires the console).
