# Finance Setup

## 1. Enable Banking account

1. Sign in at https://enablebanking.com/sign-in/ (magic link to your email)
2. Control panel: https://enablebanking.com/cp/applications
3. Create an application and note the UUID
4. Generate an RS256 private key and upload the public key to the Enable Banking console
5. Enable restricted mode (own accounts only - no contract needed)

## 2. Install CLI

```bash
cd ~/vesta/skills/finance/cli && uv tool install --force --reinstall .
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
