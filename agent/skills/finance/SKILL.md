---
name: finance
description: Use this skill when the user asks about personal finance, spending, transactions, bank balances, budgeting, or wants to see where their money went. Provides access to bank account data via Enable Banking open banking API.
---

# Finance — CLI: finance / finance-watcher

Tracks personal bank spending via Enable Banking open banking API (restricted mode — own accounts only, no commercial contract required).

## Daemon Requirement

The transaction watcher polls Enable Banking every 5 minutes and writes new transaction notifications to `~/vesta/notifications/`. It must be running at all times.

**Check if running:**
```bash
screen -ls | grep finance
```

**Start if not running:**
```bash
screen -dmS finance /root/.local/share/uv/tools/finance/bin/python -m finance_cli.transaction_watcher serve
```

**View logs (attach to screen):**
```bash
screen -r finance
# Detach: Ctrl+A, D
```

## CLI Quick Reference

```bash
# Configuration
finance config show
finance config set --app-id <uuid> --key-path ~/.finance/<uuid>.pem

# Auth (connect your bank)
finance auth login                           # prints URL, starts callback server on port 7866
finance auth status                          # check session validity
finance auth callback --url '<redirect-url>' # manual fallback if auto-catch fails
finance auth revoke                          # disconnect

# Account data
finance accounts                             # list connected accounts
finance balances                             # show current balances

# Transactions
finance transactions list                    # last 30 days
finance transactions list --days 90
finance transactions list --from 2026-01-01 --to 2026-03-21

# Spending summary
finance summary                              # by merchant, last 30 days
finance summary --month 2026-03
finance summary --days 90
finance summary --from 2026-01-01 --to 2026-03-31
```

## Transaction Watcher

The watcher (`finance-watcher` / `python -m finance_cli.transaction_watcher`) polls for new transactions and writes notification files.

- **Poll interval**: 5 minutes
- **Seen transactions**: tracked in `~/.finance/seen_transactions.json`
- **Notifications**: written to `~/vesta/notifications/finance_<timestamp>_<hash>.json`
- **First-run seeding**: on first start, if no seen file exists, it seeds all transactions from the last 30 days so old ones don't trigger notifications
- **Manual seed**: `/root/.local/share/uv/tools/finance/bin/python -m finance_cli.transaction_watcher seed`

Notification format:
```json
{
  "type": "finance",
  "source": "finance",
  "timestamp": "2026-03-21T14:30:00+00:00",
  "message": "New transaction: -€12.50 — Coffee Shop",
  "data": {
    "amount": {"amount": "12.50", "currency": "EUR"},
    "description": "Coffee Shop",
    "creditor": "",
    "debtor": "",
    "date": "2026-03-21",
    "credit_debit": "DBIT"
  }
}
```

## Auth & Consent

- **Auth method**: RS256 JWT, self-signed — JWTs generated fresh per request, no OAuth token refresh needed
- **Consent duration**: 90 days
- **Re-auth**: when expired, run `finance auth login`, visit the URL in browser, authorize your bank

**Re-auth process:**
```bash
finance auth login
# Prints URL — open in browser
# Bank authorization screen
# Callback caught automatically at https://localhost:7866/callback
# If SSL error in browser: copy the full URL from address bar, run:
finance auth callback --url '<full-redirect-url-from-browser>'
```

## Configuration

Config file: `~/.finance/config.json`
```json
{
  "app_id": "<your-enable-banking-app-uuid>",
  "key_path": "~/.finance/enablebanking-private.pem",
  "session_id": "",
  "accounts": [
    {"uid": "<account-uid>", "name": "<account-name>", "currency": "EUR"}
  ]
}
```

## Setup

### 1. Enable Banking account
1. Sign in at https://enablebanking.com/sign-in/ (magic link to your email)
2. Control panel: https://enablebanking.com/cp/applications
3. Create an application and note the UUID
4. Generate an RS256 private key and upload the public key to the Enable Banking console
5. Enable restricted mode (own accounts only — no contract needed)

### 2. Configure
```bash
finance config set --app-id <your-app-uuid> --key-path ~/.finance/enablebanking-private.pem
```

### 3. Connect your bank
```bash
finance auth login
# Authorize at the URL → callback caught on localhost:7866
```

### 4. Install CLI
```bash
cd ~/vesta/skills/finance/cli && uv tool install --force --reinstall .
```

### 5. Seed and start watcher
```bash
# Seed first (prevent notifications on old transactions)
/root/.local/share/uv/tools/finance/bin/python -m finance_cli.transaction_watcher seed

# Start daemon
screen -dmS finance /root/.local/share/uv/tools/finance/bin/python -m finance_cli.transaction_watcher serve
```

## Bank Selection Notes

- Use the `finance auth login` flow to browse available banks via Enable Banking
- For EU banks, use the country code of the bank's licensed entity (e.g. `LT` for Revolut Bank UAB, the EU-licensed entity)
- The `aspsp` name and country in `enablebanking.py` can be customized to your bank
- **Callback port**: 7866. Must be free during `finance auth login`. Port is forwarded from container to host.
- **Redirect URL**: `https://localhost:7866/callback` (HTTPS with self-signed cert — browser SSL warning is expected, just copy the URL)

## How It Works

- **JWT auth**: Each API request generates a fresh RS256 JWT signed with the private key. No token storage or refresh needed.
- **Sessions**: `finance auth login` creates a session at Enable Banking that links to your bank's consent. The `session_id` is stored in config and used for data requests.
- **Restricted mode**: Enable Banking allows linking your own bank accounts without a commercial contract. Only your linked accounts are accessible.
- **Consent**: The `valid_until` field in the auth request controls consent expiry (default 90 days).
- **Pagination**: transaction fetching automatically paginates via `continuation_key`
- **All output is JSON** — suitable for piping/parsing
