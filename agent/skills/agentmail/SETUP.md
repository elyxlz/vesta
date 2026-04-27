# agentmail setup

One-time setup, ~2 minutes. Fully autonomous on the happy path: no email,
no OTP, no clicks. Setup creates a disposable mail.tm inbox, signs up to
AgentMail with it, polls for the OTP, verifies, and discards the disposable
inbox.

## Prerequisites

That's it. No Cloudflare account, no domain, no DNS records, no email
address from the user. AgentMail's free tier covers 3 inboxes, 3,000
sends/month, webhook-based inbound.

## 1. Run the setup CLI

```bash
agentmail setup
```

Autonomous flow, in order:

1. **Disposable inbox**: POST to `https://api.mail.tm/accounts` to create a
   throwaway inbox; POST to `/token` for an auth token.
2. **AgentMail sign-up**: POST `https://api.agentmail.to/agent/sign-up` using
   the disposable email and the chosen username (default: `$AGENT_NAME`
   lowercased).
3. **OTP poll**: poll mail.tm `/messages` until an email from `agentmail`
   arrives (timeout: 3 min). Extract the OTP (typically a 6-digit number).
4. **Verify**: POST `/agent/verify` with the OTP. Persists the returned
   `AGENTMAIL_API_KEY` to `~/.bashrc` (sourced by the agent's container on
   restart).
5. **Inbox creation**: POST `/inboxes` with the chosen username. Stores the
   inbox id and full address in `~/.agentmail/config.json`.
6. **Webhook registration**: registers
   `${VESTAD_TUNNEL}/agents/${AGENT_NAME}/agentmail/webhook?secret=...` with
   AgentMail. Generates a shared `AGENTMAIL_WEBHOOK_SECRET`, persists it to
   `~/.bashrc`, and embeds it in the URL as a query param. The local service
   rejects unauthenticated callbacks.

**Verify**:

```bash
agentmail status
```

…should print the inbox id, address, and webhook URL.

### When autonomous fails

The autonomous flow can break in two realistic ways:

1. **AgentMail blocks the disposable email domain.** Sign-up succeeds but no
   OTP arrives; setup times out at step 3.
2. **mail.tm is down or rate-limiting.** Step 1 fails immediately.

Both cases hard-exit with a clear message. Two recovery paths:

- `agentmail setup --prompt`: manual mode. Asks for an email and OTP.
- Browser fallback: use the `browser` skill to sign up at
  https://console.agentmail.to, generate an API key, then
  `export AGENTMAIL_API_KEY=<key> && agentmail setup --skip-signup`.

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
