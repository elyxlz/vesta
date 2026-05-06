# Finance Setup

## 1. Enable Banking account

1. Sign in at https://enablebanking.com/sign-in/ (magic link to your email)
2. Control panel: https://enablebanking.com/cp/applications
3. Create an application and note the UUID
4. Generate an RS256 private key and upload the public key to the Enable Banking console
5. Enable restricted mode (own accounts only, no contract needed)

## 2. Install CLI

```bash
cd ~/agent/skills/finance/cli && uv tool install --force --reinstall .
```

## 3. Configure

```bash
finance config set --app-id <your-app-uuid> --key-path ~/.finance/enablebanking-private.pem
```

## 4. Connect your bank

```bash
finance auth login
# Authorize at the URL → callback caught on localhost:7866
```

### Production redirect URL

Enable Banking's production app registration form rejects every form of `localhost`
(`http://`, `https://`, `127.0.0.1`) with "unsupported scheme" / "invalid url" errors,
so the localhost default only works for the sandbox / local dev path.

For a real registered app, override the redirect with the `FINANCE_REDIRECT_URL`
env var (set it in the agent env so the CLI inside the container picks it up):

```bash
export FINANCE_REDIRECT_URL="https://<your-public-host>/callback"
```

The natural fit on Vesta is a vestad public service tunnel: register a public
service for the agent, point Enable Banking at
`https://<vestad-tunnel>/agents/$AGENT_NAME/<service-name>/callback`, and run a
small handler on the assigned port that pipes the captured `?code=...` URL
through `finance auth callback --url <full-url>`. The handler itself is not
shipped yet, see issue #464 for the followup.

## 5. Seed and start watcher

```bash
# Seed first (prevent notifications on old transactions)
/root/.local/share/uv/tools/finance/bin/python -m finance_cli.transaction_watcher seed

# Start daemon
screen -dmS finance /root/.local/share/uv/tools/finance/bin/python -m finance_cli.transaction_watcher serve
```

## 6. Add to restart.md

```
screen -dmS finance /root/.local/share/uv/tools/finance/bin/python -m finance_cli.transaction_watcher serve
```
