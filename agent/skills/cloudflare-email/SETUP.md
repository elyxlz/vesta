# cloudflare-email setup

One-time setup. Takes ~10 minutes. The agent runs interactively, you paste a
token and confirm a few choices.

## Prerequisites

- A Cloudflare account
- A domain on that Cloudflare account (e.g. `vesta.run`). The domain's name
  servers must be pointing at Cloudflare so email routing can attach MX records.
- `wrangler` CLI installed locally for the Worker deploy. The setup will install
  it via `npm i -g wrangler` if missing.

## 1. Create a Cloudflare API token

In the Cloudflare dashboard:

1. Go to **My Profile** → **API Tokens** → **Create Token**
2. Use **Custom Token**
3. Permissions:
   - **Account** → **Email** → **Edit** (manages Email Routing + Email Send)
   - **Account** → **Workers Scripts** → **Edit** (deploys the inbound Worker)
   - **Zone** → **Email Routing** → **Edit** (per-domain routing rules)
   - **Zone** → **DNS** → **Edit** (auto-add MX/SPF/DKIM)
4. Account/Zone resources: scope to the specific account + the email domain only
5. Click **Continue to summary** then **Create Token**
6. Copy the token. It's shown once.

## 2. Stash the token in keeper

```bash
keeper store cloudflare/api-token "<paste-the-token>"
```

## 3. Run the setup CLI

```bash
cloudflare-email setup
```

The agent will:

1. Read the token from keeper
2. Verify the token works and list domains on the account
3. Ask which domain to use (default: `vesta.run` if present, else first listed)
4. Ask for the agent's email local-part (default: `$AGENT_NAME`, lowercased)
5. Enable Email Routing on the chosen zone (adds MX records, configures SPF)
6. Create a catch-all routing rule that forwards `${local}@${domain}` and
   `${local}+*@${domain}` to the inbound Worker
7. Deploy the inbound Worker (in `~/agent/skills/cloudflare-email/worker/`),
   wired to call the local `cloudflare-email` service via the public vestad
   tunnel
8. Generate a shared secret, stash it as `cloudflare-email/worker-secret` in
   keeper, set as a Worker secret too
9. Write `CF_EMAIL_DOMAIN=<chosen-domain>` and `CF_EMAIL_ADDRESS=<full>` to
   `~/.bashrc`

## 4. Register and start the local service

```bash
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services \
  -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"cloudflare-email","public":true}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")
screen -dmS cloudflare-email cloudflare-email serve --port $PORT
```

Add to `~/agent/prompts/restart.md`:

```bash
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' -d '{"name":"cloudflare-email","public":true}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])") && screen -dmS cloudflare-email cloudflare-email serve --port $PORT
```

The `public: true` is required: the Worker needs to reach the service through
the vestad tunnel.

## 5. Send a test email

```bash
cloudflare-email send --to <your-personal-email> --subject "test from athena" --body "hello"
```

Check it lands. Reply to it from your personal email, then watch for the
inbound notification:

```bash
ls -la ~/agent/notifications/ | grep cloudflare-email
```

## Token rotation

If the API token leaks or you want to rotate:

```bash
keeper store cloudflare/api-token "<new-token>"
cloudflare-email setup --reconcile
```

The reconcile flag re-verifies routing + Worker + secret without re-prompting.

## Uninstall

```bash
cloudflare-email teardown
```

Removes the routing rule, deletes the Worker, clears keeper entries. The MX
records and Email Routing zone setting are left in place since other workflows
may use them.
