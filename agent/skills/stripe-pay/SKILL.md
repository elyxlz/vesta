---
name: stripe-pay
description: Use when the user wants the agent to make a payment on their behalf via Stripe Link Wallet for Agents. Always asks for explicit per-charge approval. Requires `stripe-pay authorize` setup first.
---

# stripe-pay - CLI: `stripe-pay`

Lets the agent spend on the user's behalf through Stripe's "Link Wallet for Agents" + "Issuing for Agents" APIs (April 2026 release).

Two commands. No history viewer, no spend-cap config (caps live in Stripe Link), no auto-approve.

```bash
stripe-pay authorize                                          # one-time OAuth setup
stripe-pay charge --amount 12.50 --currency USD \
                  --merchant "Some Shop" --reason "domain renewal"
```

## Trigger

Invoke this skill when:
- The user asks the agent to buy something for them ("order me X", "pay this invoice", "renew my domain")
- The user explicitly mentions Stripe / Link wallet / agent wallet
- A workflow needs to spend money on the user's behalf at a merchant that takes cards

## Skip

Not for sending money to people (merchants only, not P2P) or read-only expense logging (use the `enable-banking` skill). If `stripe-pay authorize` has not run, `charge` errors clearly and you tell the user to set up first.

## Setup

See [SETUP.md](SETUP.md). One-time:
1. Create a Stripe Restricted API Key (or use the Agent Toolkit OAuth client)
2. Run `stripe-pay authorize` and approve in the Link app
3. Configure spend caps in the Link app (per-charge / daily / monthly)

## Usage

### Asking the user to authorize

If `stripe-pay authorize` has not been run, the `charge` command exits with a clear error. The agent should explain what authorize does and link to SETUP.md.

### Making a charge

```bash
stripe-pay charge \
    --amount 24.99 \
    --currency USD \
    --merchant "Acme Domains" \
    --reason "renewing example.com for 1 year"
```

Flow:
1. The CLI sends an approval prompt to the user via their **primary channel**
   (auto-detected from `MEMORY.md` Primary Channel default; falls back to WhatsApp).
   The prompt includes amount, currency, merchant, reason, and a 5-minute deadline.
2. The CLI blocks waiting for the user's reply. Approval keywords: `yes`, `y`,
   `go`, `confirm`, `ok`, or a thumbs-up / check-mark emoji. Rejection keywords:
   `no`, `n`, `stop`, `cancel`.
3. On approval the CLI calls Stripe Issuing-for-Agents to mint a single-use
   virtual card scoped to that amount + merchant, and prints the card details
   to stdout as JSON. It also logs the transaction to `~/.stripe-pay/history.jsonl`.
4. On rejection / timeout the CLI exits non-zero, logs the abort, and the agent
   tells the user.

### Output (success)

```json
{
  "status": "approved",
  "charge_id": "ch_1XYZ...",
  "card": {
    "number": "4242...4242",
    "exp_month": 12,
    "exp_year": 2026,
    "cvc": "***"
  },
  "amount": 24.99,
  "currency": "USD",
  "merchant": "Acme Domains"
}
```

The agent can hand this card detail to a browser/checkout flow, or use Stripe's
Buy-with-Link merchant integration if the merchant supports it.

### Output (rejected / timed out)

```json
{ "status": "rejected", "reason": "user_declined" }
{ "status": "timeout",  "reason": "no_reply_in_5_minutes" }
```

## Caveats

- **Always asks the user. Never silent.** This is a hard rule. Do not try to
  bypass the approval prompt.
- **Charges do NOT create vesta tasks.** They log to `~/.stripe-pay/history.jsonl`
  only. Don't write a task for a charge.
- **If Stripe's Link-side cap is exceeded**, Stripe forces a Link-app approval on
  top of ours. The CLI surfaces that requirement in the channel prompt.
- **Card details are ephemeral.** The skill never persists raw card numbers,
  they live in stdout for one process lifetime. The agent should pass them
  straight to the merchant flow, not save them.
- **Currency** uses ISO 4217 codes (`USD`, `EUR`, `GBP`, ...). Amounts are in
  major units (e.g. `24.99` not `2499`).
- **One charge at a time.** Don't fan out parallel `stripe-pay charge` calls,
  the user will get multiple WhatsApp prompts and approvals will get tangled.

## Logs

`~/.stripe-pay/history.jsonl`: one JSON object per line:

```json
{"ts":"2026-05-06T10:11:12Z","amount":24.99,"currency":"USD","merchant":"Acme Domains","reason":"renewing example.com","status":"approved","charge_id":"ch_1XYZ"}
```

Statuses: `approved`, `rejected`, `timeout`, `error`.

## Files

- `~/.stripe-pay/credentials.json`: OAuth tokens (chmod 600)
- `~/.stripe-pay/history.jsonl`: append-only charge log
