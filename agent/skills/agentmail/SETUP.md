# agentmail setup

Fully autonomous on the happy path: `agentmail setup` creates a disposable
mail.tm inbox, signs up to AgentMail with it, polls for the OTP, verifies,
and discards the disposable inbox. ~2 minutes; no email, no OTP, no clicks.

No prerequisites. AgentMail's free tier (3 inboxes, 3,000 sends/month,
webhook inbound) covers basic agent send + receive without a Cloudflare
account, a domain, or DNS records.

## 1. Run setup

```bash
agentmail setup
```

What happens, in order:

1. **Disposable inbox** created at mail.tm (no signup required by them).
2. **AgentMail sign-up** at `POST /v0/agent/sign-up` using the disposable
   email. Returns `api_key` + `inbox_id` immediately and auto-creates an
   inbox at `${username}@agentmail.to` (default username:
   `$AGENT_NAME` lowercased).
3. **OTP poll** on the disposable inbox until AgentMail's verification
   email arrives (timeout: 3 min); a 6-digit code is extracted via regex.
4. **Verify** at `POST /v0/agent/verify` with `Bearer ${api_key}` and
   `{otp_code}`. Persists `AGENTMAIL_API_KEY` to `~/.bashrc`.
5. **Webhook registration** at `POST /v0/webhooks` pointing at
   `${VESTAD_TUNNEL}/agents/${AGENT_NAME}/agentmail/webhook?secret=…`.
   Generates `AGENTMAIL_WEBHOOK_SECRET`, persists to `~/.bashrc`.

**Verify**: `agentmail status` should print the inbox id, address, and
webhook URL.

### When autonomous fails

The autonomous flow can break in two ways:

- **AgentMail blocks the disposable email domain.** Sign-up succeeds but
  no OTP arrives; setup times out at step 3.
- **mail.tm is down or rate-limiting.** Step 1 fails immediately.

Both hard-exit with a clear message naming the likely cause. Two
recovery paths:

```bash
# Manual: prompts for your email and the OTP you receive
agentmail setup --prompt

# Pre-set key (e.g. from console signup via the browser skill)
export AGENTMAIL_API_KEY=<paste-key>
agentmail setup --skip-signup
```

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

A successful send returns `{"ok": true, "result": {"message_id": "<...>", ...}}`.
Check the recipient inbox to confirm delivery, then reply from there and
watch for the inbound notification:

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

Deletes the inbox via the AgentMail API and clears
`~/.agentmail/config.json`. The AgentMail account itself is left alone (an
account can hold multiple inboxes; deleting the account requires the
console).
