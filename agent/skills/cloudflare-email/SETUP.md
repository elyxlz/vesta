# cloudflare-email setup

One-time setup, ~10 minutes. Two interactive prompts: pasting the API token,
and confirming the domain + local-part.

## Prerequisites

- A Cloudflare account.
- A domain on that account (e.g. `vesta.run`) with name servers pointing at
  Cloudflare. Email Routing (inbound) and Email Sending (outbound) attach DNS
  records (MX for routing; SPF + DKIM for sending), so Cloudflare must own DNS
  for the zone.
- `node` + `npm` on PATH. Setup runs `npm install` in `worker/` to bundle
  `postal-mime`, the MIME parser the inbound Worker uses.
- `wrangler` CLI. Install with `npm i -g wrangler` if missing.

## 1. Create a Cloudflare API token

In the Cloudflare dashboard:

1. Go to **My Profile** → **API Tokens** → **Create Token**.
2. Use **Custom Token**.
3. Permissions:
   - **Account** → **Email** → **Edit** (Email Routing + Email Sending)
   - **Account** → **Workers Scripts** → **Edit** (deploy the inbound Worker)
   - **Zone** → **Zone** → **Read** (list zones to find your domain)
   - **Zone** → **Email Routing** → **Edit** (per-domain routing rules)
   - **Zone** → **DNS** → **Edit** (auto-add MX / SPF / DKIM)
4. Account & Zone resources: scope to the specific account + the email domain.
5. **Continue to summary** → **Create Token**. Copy the token now; it's shown once.

## 2. Run the setup CLI

```bash
cloudflare-email setup
```

Setup walks through, in order:

1. Prompt for the API token (hidden input). Persists `CF_API_TOKEN` to
   `~/.bashrc` so it survives container restarts. Verifies the token, lists
   zones, prompts for domain (default `vesta.run` if
   present) and local-part (default `$AGENT_NAME` lowercased).
2. **Inbound:** enable Email Routing on the zone (adds MX records).
3. **Outbound:** check `wrangler email sending list`; if the domain isn't
   onboarded, run `wrangler email sending enable <domain>` and print the
   required SPF + DKIM records via `wrangler email sending dns get <domain>`.
4. `npm install` in `worker/`, then `wrangler deploy` the Worker with
   `INBOUND_URL` pointing at the agent's vestad tunnel.
5. Generate a worker secret, persist `CF_WORKER_SECRET` to `~/.bashrc`, set
   it on the deployed Worker via `wrangler secret put`.
6. Create two routing rules: a literal rule for `${local}@${domain}` and a
   wildcard literal rule for `${local}+*@${domain}`, both pointing at the
   Worker. Before creating, setup checks whether either address is already
   routed by a foreign rule (another agent, or a stale leftover); if so, it
   prompts:
   - **change**: pick a different local-part and re-check.
   - **abort**: exit without touching anything.

   Setup never deletes a foreign rule, since that would silently break the
   other agent's inbound mail. If you're sure the conflicting rule is stale,
   delete it by hand in the Cloudflare dashboard (or via
   `wrangler email routing rules delete`) and re-run setup.
7. Persist `domain`, `address`, zone/account IDs, and worker name to
   `~/.cloudflare-email/config.json`. Also write `CF_EMAIL_DOMAIN` and
   `CF_EMAIL_ADDRESS` to `~/.bashrc` for convenience.

After this completes, **DNS for outbound may take 5-15 minutes to
propagate**. Inbound works immediately.

**Verify**: `cloudflare-email status` should show `domain`, `address`, and
`worker_name` filled in.

## 3. Register and start the local service

The Worker reaches the local FastAPI service through the public vestad
tunnel; that's why the service must be registered with `"public": true`.

```bash
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services \
  -H "X-Agent-Token: $AGENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"cloudflare-email","public":true}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")

screen -dmS cloudflare-email cloudflare-email serve --port $PORT
```

Append the same two-line block to `~/agent/prompts/restart.md` so the
service comes back up after a container restart.

**Verify**: `curl http://127.0.0.1:$PORT/health` should return
`{"ok": true, "address": "<your-address>"}`.

## 4. Send a test email

```bash
cloudflare-email send \
  --to <your-personal-email> \
  --subject "test from $AGENT_NAME" \
  --body "hello" \
  --html-file /dev/stdin <<< "<p>hello</p>"
```

If this returns `{"ok": false, "error": "...sender domain not verified..."}`,
the SPF / DKIM records from step 3 haven't propagated yet. Check with:

```bash
wrangler email sending dns get <domain>
```

…and wait. Once the test send lands, reply to it from your personal inbox
and confirm the inbound notification:

```bash
ls -la ~/agent/notifications/ | grep cloudflare-email
```

## Token rotation

If the token leaks or you want to rotate, edit `~/.bashrc` and replace the
`export CF_API_TOKEN=...` line with the new value, then:

```bash
source ~/.bashrc
cloudflare-email reconcile
```

`reconcile` re-applies the routing rules and re-verifies the Worker secret
without re-prompting for the domain or local-part.

## Uninstall

```bash
cloudflare-email teardown
```

Removes both routing rules and deletes the Worker. MX records and the Email
Routing zone setting stay in place, since other workflows on the same domain
may need them. To fully decommission, also run
`wrangler email sending disable <domain>` and remove the routing rule + DNS
records in the Cloudflare dashboard.
