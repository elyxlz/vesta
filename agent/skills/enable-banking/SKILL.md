---
name: enable-banking
description: Personal bank spending, transactions, balances via Enable Banking open banking (EU/EEA only, no UK).
---

# Enable Banking - CLI: finance / finance-watcher

Tracks personal bank spending via Enable Banking open banking API.

## Coverage and limitations

Enable Banking is a Finland-licensed AISP operating under EU/EEA PSD2. It does **not** cover UK residents linking UK bank accounts: the UK consent flow returns "Due to local financial regulation you are not currently able to grant consent." Confirmed against a UK PSU attempting to link Revolut Bank UAB (LT) in May 2026.

For UK users, workable alternatives outside the EB API are per-bank developer APIs (e.g. Monzo, free for own-account use), manual CSV imports, or a UK-licensed AISP with personal-tier API access (as of May 2026 there is no straightforward free auto-aggregator for UK individuals).

**That block is about WHERE the user consents from, not a permanent per-bank ban.** The same Revolut Bank UAB (LT) link that failed for a UK-based PSU in May 2026 succeeded in July 2026 for the same user consenting from the EU (`--aspsp-name Revolut --aspsp-country LT`, 4 accounts, 90-day consent). If a user's circumstances have changed, retry before repeating a documented limitation back at them: a "confirmed" failure can be circumstantial rather than structural.

## A suggestive config key is not evidence of what the code reads

`~/.finance/config.json` can accumulate vestigial keys from unrelated/abandoned setups (e.g. `environment: "sandbox"`, a `client_id`, a `redirect_uri`, stray `access_token`/`refresh_token` from a different provider's SDK). **This CLI reads none of them.** It authenticates with exactly three things: `app_id`, `key_path` (RS256 PEM), and `session_id`.

Do not infer the liveness of a connection from a string in a config file. Read the code to see which keys the client actually consumes, or confirm against the API. Getting this backwards in either direction is costly, and calling REAL financial data "fake sandbox data" is just as damaging as trusting fake data: it can push someone to act on a balance you told them wasn't real. If you truly need to know whether data is live, the decisive test is a fresh user-consented session: if it returns the same values, they were always live.

## Transaction Watcher (daemon)

The watcher (`finance-watcher` / `python -m finance_cli.transaction_watcher`) polls Enable Banking every 5 minutes and writes new transaction notifications to `~/agent/notifications/<time_ns>-finance-message.json`. It must be running at all times.

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

- **Seen transactions**: tracked in `~/.finance/seen_transactions.json`
- **First-run seeding**: on first start, if no seen file exists, it seeds all transactions from the last 30 days so old ones don't trigger notifications
- **Manual seed**: `/root/.local/share/uv/tools/finance/bin/python -m finance_cli.transaction_watcher seed`

Notifications carry `source: "finance"`, `type: "finance"`, a `timestamp`, a human-readable `message`, and `data` with the transaction fields: `amount` (`{amount, currency}`), `description`, `creditor`, `debtor`, `date`, `credit_debit`.

## CLI Quick Reference

```bash
# Configuration
finance config show
finance config set --app-id <uuid> --key-path ~/.finance/<uuid>.pem
finance config set --aspsp-name Revolut --aspsp-country LT   # which bank to connect (persists; survives reinstalls)

# Auth (connect your bank)
finance auth login                           # prints URL, starts callback server on port 7866 (forwarded from container to host)
finance auth status                          # check session validity
finance auth callback --url '<redirect-url>' # manual fallback (see Re-auth below)
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

## Auth & Consent

- **Auth method**: each API request generates a fresh RS256 self-signed JWT. No OAuth token storage or refresh needed.
- **Sessions**: `finance auth login` creates a session at Enable Banking linked to your bank's consent. The `session_id` is stored in config and used for data requests.
- **Restricted mode**: Enable Banking allows linking your own bank accounts without a commercial contract; only your linked accounts are accessible.
- **Consent duration**: 90 days (the `valid_until` field in the auth request controls expiry).
- **Re-auth**: when consent expires, run `finance auth login` and authorize your bank in the browser. The callback is caught automatically at `https://localhost:7866/callback`; on a browser SSL error, copy the full redirect URL from the address bar and pass it to `finance auth callback --url '<url>'`.
- **Pagination**: transaction fetching automatically paginates via `continuation_key`.
- **All output is JSON**, suitable for piping/parsing.

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

See [SETUP.md](SETUP.md) for initial configuration instructions.

## Bank Selection Notes

- Browse available banks via the `finance auth login` flow, then set your bank with `finance config set --aspsp-name <name> --aspsp-country <cc>`.
- For EU banks, use the country code of the bank's **licensed entity**, not the user's country (e.g. `LT` for Revolut Bank UAB). The `ASPSP_NAME` / `ASPSP_COUNTRY` constants in `enablebanking.py` are only the fallback default when config is unset.
