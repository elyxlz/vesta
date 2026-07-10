# Tricount Skill Setup

## Prerequisites

- Python 3.11+
- uv (https://docs.astral.sh/uv/)
- A Tricount sharing link / token for any group you want to access

## Step 1: Install the CLI

```bash
uv tool install --editable ~/agent/skills/tricount/cli
```

Verify:
```bash
tricount --help
```

## Step 2: Register this device

Tricount uses **anonymous device registration** — no Tricount account or password is needed. This creates a unique device identity and gets an auth token.

```bash
tricount auth register
```

Credentials are saved to `~/.tricount/credentials.json` (mode 600).

## Step 3: Join a tricount

Get the sharing token from your Tricount group's sharing URL or QR code. The token looks like `tABC123xyz...` and appears at the end of a `tricount.com/en/topic/...` URL.

```bash
tricount join tYourTokenHere
```

## Step 4: Use it

```bash
# List your tricounts
tricount list

# See expenses
tricount expenses "Trip to Berlin"

# See who owes what
tricount balances "Trip to Berlin"

# Add an expense
tricount add-expense "Trip to Berlin" \
  --description "Hotel" \
  --amount 150.00 \
  --payer "Alice"
```

## Credential storage

| File | Purpose |
|------|---------|
| `~/.tricount/credentials.json` | Auth token, user_id, device UUID, RSA public key |

To start fresh (new device identity):
```bash
tricount auth logout
tricount auth register
# Then re-join your tricounts
```

## Troubleshooting

**"Not authenticated" error:** Run `tricount auth register` first.

**"Tricount not found" error:** Run `tricount join <token>` with the token from the sharing URL.

**Payer name not found:** Run `tricount show <tricount>` to see the exact member names as stored in Tricount.

**API changes:** This CLI uses an unofficial, reverse-engineered API. If it stops working, check https://github.com/elrandar/tricount-api for updates.
