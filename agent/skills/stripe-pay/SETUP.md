# stripe-pay Skill Setup

One-time setup so the agent can charge a Stripe Link wallet on the user's behalf.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- A Stripe account with **Link** enabled
- The user's preferred channel skill installed and authenticated (one of: `whatsapp`, `telegram`, `app-chat`)

## Step 1: Install the CLI

```bash
uv tool install ~/agent/skills/stripe-pay/cli
```

This installs the `stripe-pay` binary onto your `PATH`.

## Step 2: Get Stripe credentials

You need a **Restricted API Key** scoped for agent payments.

1. Go to <https://dashboard.stripe.com/apikeys>
2. Click "Create restricted key"
3. Name it `vesta-agent` (or similar)
4. Grant these permissions:
   - **Issuing**: Cards `Write`, Authorizations `Read`
   - **Link**: Wallet `Write` (for the OAuth flow)
   - **Charges**: `Write` (so spend requests can settle)
5. Copy the `rk_live_...` (or `rk_test_...`) key

Store it once:

```bash
mkdir -p ~/.stripe-pay && chmod 700 ~/.stripe-pay
printf '%s' 'rk_live_...' > ~/.stripe-pay/api_key
chmod 600 ~/.stripe-pay/api_key
```

(`stripe-pay authorize` reads this on first run.)

## Step 3: Authorize the agent in your Link wallet

```bash
stripe-pay authorize
```

This opens your browser to Stripe's Link OAuth consent flow. Sign in to Link
and approve the agent. You'll be redirected to a localhost callback that the
CLI captures, and the resulting refresh token is saved to
`~/.stripe-pay/credentials.json` (mode 600).

This is idempotent — re-running it re-opens the browser to refresh the token.

## Step 4: Configure spend caps in the Link app

Open the Link app (iOS / Android / web) and set caps for the connected agent:

- **Per-charge cap** (e.g. $50)
- **Daily cap** (e.g. $200)
- **Monthly cap** (e.g. $1000)
- **Allowed merchant categories** (optional)

Caps live in Stripe Link, not in this skill. If a charge exceeds a cap, Stripe
will require a second approval inside the Link app on top of the per-charge
prompt the agent sends to your channel.

## Step 5: Test

Send yourself a tiny test charge:

```bash
stripe-pay charge --amount 1 --currency USD \
                  --merchant "stripe-pay smoke test" \
                  --reason "verifying setup"
```

You should:
1. Get an approval prompt on your primary channel (WhatsApp / Telegram / app-chat)
2. Reply `yes`
3. See a JSON blob with a single-use card on stdout
4. See an `approved` line in `~/.stripe-pay/history.jsonl`

If you get an error about "no credentials", repeat Step 3.

## Step 6: Tell the agent

Mention to your vesta that the skill is set up. Future charge requests like
"renew my domain" will route through `stripe-pay charge`.

## Optional: scope to test mode first

If you want to verify the flow without real money, use a **test mode** restricted
key (`rk_test_...`) in Step 2 and authorize the agent against the Stripe
Link **test environment**. Charges will succeed without moving real funds.

## Troubleshooting

- `error: no_credentials` — run `stripe-pay authorize`.
- `error: token_expired` — re-run `stripe-pay authorize` to refresh.
- Approval prompt never arrives — confirm your primary channel daemon is
  running (`screen -ls` should show `whatsapp` / `telegram` / `app-chat`).
- Charge succeeds in Stripe but stdout shows an error — check
  `~/.stripe-pay/history.jsonl` for the recorded `charge_id` and reconcile in
  the Stripe dashboard.
