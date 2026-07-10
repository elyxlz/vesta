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

## Watcher daemon (notifications)

Like the other daemon skills (microsoft/telegram/tasks), tricount can run a long-lived watcher that polls all joined tricounts and writes a notification when anything changes.

```bash
tricount serve --notifications-dir ~/agent/notifications [--interval SECONDS]
```

- `--notifications-dir` (required): where notification JSON files are written.
- `--interval` (default 120): seconds between polls. Keep it gentle on the unofficial API.

It writes one JSON file per change into the notifications dir, matching the shared notification schema (`source`, `type`, fields, `timestamp`; filename `<micros>-tricount-<type>.json`). `source` is `tricount` and `interrupt` is `false` (these pool, they are not urgent).

Change detection uses a state file at `~/.tricount/watch-state.json` mapping each tricount to a content hash per entry (amount, description, payer, allocations, deleted flag) plus the member list. Each poll diffs current vs stored and emits:

| type | when | example message |
|------|------|-----------------|
| `add` | new expense | `Elio added 'Dinner' GBP 40.00 to 'angels'` |
| `edit` | an expense's amount/description/payer/split changed | `Bob edited 'Taxi' in 'angels'` |
| `delete` | an expense was removed or marked deleted | `Elio's expense 'Beers' GBP 12.00 was deleted from 'angels'` |
| `settled` | a settlement/reimbursement (BALANCE/INCOME) entry | `Alex settled up with Louis for GBP 20.00 in 'angels'` |
| `member_joined` | a new member joined a tricount | `Charlie joined 'angels'` |

**First-run seed is silent.** If the state file is missing, or a tricount is newly seen, its current state is recorded with no notifications, so pre-existing history never notifies. Only post-seed deltas fire. State is saved atomically after each successful poll, so nothing double-notifies. The loop never crashes on a transient API/auth error: it logs to stderr and continues.

Run it in the background alongside the other daemons:

```bash
screen -dmS tricount tricount serve --notifications-dir ~/agent/notifications
```

## Notes

- All output is JSON
- Install via: `uv tool install --editable <path-to-skill>/cli`
- The Tricount API is unofficial (reverse-engineered from the Android app). It may change without notice.
- Balances are computed client-side (no dedicated balance endpoint).
- Any device with the sharing token can read and write expenses — access is trust-based.
