---
name: tricount
description: Tricount shared-expense / bill-splitting CLI. List tricounts, view expenses and balances, add expenses. No official API — uses reverse-engineered Tricount (bunq) REST API.
---

# Tricount — CLI: tricount

Manage shared expenses via Tricount (bunq). List your tricounts, view expenses and balances, add new expenses.

## Setup

See [SETUP.md](SETUP.md) for installation.

## Auth

Tricount uses **anonymous device registration** — no Tricount account or password needed. The CLI generates an RSA key pair and registers as an anonymous device, receiving an auth token that persists across sessions.

```bash
# Register this device (one-time, no account needed)
tricount auth register

# Check status
tricount auth status

# Remove credentials
tricount auth logout
```

Credentials stored at: `~/.tricount/credentials.json` (mode 600)

To use a specific Tricount group, you need its **sharing token** (the `tXXX...` code from the Tricount sharing URL). Join it once:

```bash
tricount join tABC123xyz
```

After joining, the tricount appears in `tricount list` for all future commands.

## Commands

### List tricounts

```bash
tricount list
```

Lists all tricounts this device has joined (title, ID, currency, member count, expense count).

### Join a tricount

```bash
tricount join <token>
```

The token is the `tXXX...` code from a Tricount sharing URL or QR code.

### Show tricount details

```bash
tricount show <tricount>
```

`<tricount>` can be a numeric ID, public token, or title (case-insensitive).

### List expenses

```bash
tricount expenses <tricount>
```

Returns all active expenses, newest first (description, amount, payer, date, per-member split).

### Show balances

```bash
tricount balances <tricount>
```

Net balance per member. Positive = owed money; negative = owes money.

### Add an expense

```bash
tricount add-expense <tricount> \
  --description "Dinner" \
  --amount 60.00 \
  --payer "Alice" \
  --split "Alice,Bob,Carol"   # optional: defaults to all active members
```

Options:
- `--description` / `-d` — expense label (required)
- `--amount` / `-a` — positive total amount in the tricount's currency (required)
- `--payer` / `-p` — name (or UUID) of the member who paid (required)
- `--split` / `-s` — comma-separated names/UUIDs to split among; omit for equal split among all
- `--date` — date string `YYYY-MM-DD HH:MM:SS.000000`; defaults to now

## Notes

- All output is JSON
- Install via: `uv tool install --editable <path-to-skill>/cli`
- The Tricount API is unofficial (reverse-engineered from the Android app). It may change without notice.
- Balances are computed client-side (no dedicated balance endpoint).
- Any device with the sharing token can read and write expenses — access is trust-based.
