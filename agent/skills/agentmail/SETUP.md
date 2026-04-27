# agentmail setup

Fully autonomous on the happy path: `agentmail setup` provisions an
AgentMail account, inbox, and webhook end-to-end, plus installs the
official AgentMail CLI for passthrough, all without asking the user for
anything. ~2 minutes.

No prerequisites beyond `node`/`npm` (used to install the official CLI
locally). AgentMail's free tier (3 inboxes, 3,000 sends/month, webhook
inbound) covers basic agent send + receive without a Cloudflare account,
a domain, or DNS records.

## 1. Run setup

```bash
agentmail setup
```

What happens, in order:

1. **Disposable inbox** created at mail.tm (no signup required).
2. **AgentMail sign-up** via the official Python SDK
   (`client.agent.sign_up`). Returns `api_key` + `inbox_id` immediately
   and auto-creates an inbox at `${username}@agentmail.to`. Default
   username: `$AGENT_NAME` lowercased.
3. **OTP poll** on the disposable inbox until AgentMail's verification
   email arrives (timeout: 3 min). A 6-digit code is extracted via regex.
4. **Verify** via `client.agent.verify` (Bearer-authed with the api_key).
   Persists `AGENTMAIL_API_KEY` to `~/.bashrc`.
5. **Install official CLI** locally to `~/.agentmail/node_modules/`
   (`npm install --prefix ~/.agentmail agentmail-cli`). Idempotent. Done
   before the webhook step so partial failures still leave the
   passthrough usable.
6. **Webhook registration** via `client.webhooks.create` pointing at
   `${VESTAD_TUNNEL}/agents/${AGENT_NAME}/agentmail/webhook?secret=…`.
   Generates `AGENTMAIL_WEBHOOK_SECRET`, persists to `~/.bashrc`.

**Verify**: `agentmail status` should print the inbox id, address, and
webhook URL.

### When autonomous fails

The autonomous flow can break in two ways:

- **AgentMail blocks the disposable email domain.** Sign-up succeeds but
  no OTP arrives; setup times out at step 3.
- **mail.tm is down or rate-limiting.** Step 1 fails immediately.

Both hard-exit with a clear message naming the likely cause. Two recovery
paths:

```bash
# Manual: prompts for your email and the OTP you receive
agentmail setup --prompt

# Pre-set key (e.g. from console signup via the browser skill)
export AGENTMAIL_API_KEY=<paste-key>
agentmail setup --skip-signup
```

## 2. Register and start the local webhook receiver

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

The send command is provided by the official AgentMail CLI, transparently
passed through by our wrapper:

```bash
INBOX_ID=$(agentmail status | python3 -c "import sys,json; print(json.load(sys.stdin)['inbox_id'])")
agentmail inboxes:messages send \
  --inbox-id "$INBOX_ID" \
  --to <your-personal-email> \
  --subject "test from $AGENT_NAME" \
  --text "hello"
```

Reply from your personal inbox, then watch for the inbound notification:

```bash
ls -la ~/agent/notifications/ | grep agentmail
```

A new file should appear within seconds of the reply landing.

## Token rotation

Edit `~/.bashrc`, replace the `export AGENTMAIL_API_KEY=...` line with the
new value, then:

```bash
source ~/.bashrc
agentmail status
```

If `status` still resolves the inbox + webhook, you're done. No
re-registration needed.

## Uninstall

```bash
agentmail teardown
```

Deletes the inbox + webhook via the AgentMail API and clears
`~/.agentmail/config.json`. The AgentMail account itself and the locally
installed npm CLI are left in place (an account can hold multiple
inboxes; deleting the account requires the console).
