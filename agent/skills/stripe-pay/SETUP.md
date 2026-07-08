# stripe-pay Skill Setup

One-time setup so Vesta can pay merchants on your behalf through Stripe's **Link
for Agents**, using the official `@stripe/link-cli`. Your real card is never
exposed: each purchase mints a single-use credential that Stripe releases only
after you approve it in your Link app.

## Prerequisites

- Node.js 18+ (already present in the agent container)
- A Stripe **Link** account, with the Link app on your phone (iOS / Android) or web
- The user (you) able to receive Link approval push notifications

## Step 1: Install the Link CLI

```bash
npm i -g @stripe/link-cli
link-cli --version
```

(If you would rather not install globally, every command in the skill also runs as
`npx -y @stripe/link-cli <args>`.)

## Step 2: Connect the agent to your Link wallet

```bash
link-cli auth login --client-name "Vesta"
```

This prints a verification URL and a short phrase. Open the URL, sign in to Link,
and enter the phrase to approve the connection. `--client-name "Vesta"` is how the
connection shows up in your Link app, so you can recognise and revoke it later.

On a headless box where the agent cannot relay the code interactively, either:

- run `link-cli auth login --client-name "Vesta" --interval 5 --timeout 300`, which
  prints the code immediately and polls until you approve, or
- set `LINK_ACCESS_TOKEN` (and `LINK_REFRESH_TOKEN`) in the agent's environment if
  you already hold tokens.

Confirm it worked:

```bash
link-cli auth status
```

## Step 3: Set your spend caps in the Link app

Open the Link app and set caps for the connected "Vesta" agent:

- Per-charge cap (e.g. $50)
- Daily cap (e.g. $200)
- Monthly cap (e.g. $1000)

Caps are enforced by Stripe, not by this skill. A spend over a cap is refused, and
Stripe will tell you why in the approval prompt.

## Step 4: Rehearse in test mode

Run a spend request in Stripe test mode (no real money, uses card 4242...):

```bash
link-cli spend-request create \
  --merchant-name "stripe-pay smoke test" \
  --merchant-url "https://example.com" \
  --context "Test-mode rehearsal to confirm Vesta can request a spend approval and retrieve a single-use card credential end to end." \
  --amount 100 \
  --request-approval --test --format json
```

You should get a Link approval push. Approve it, then retrieve the (test) card:

```bash
link-cli spend-request retrieve <lsrq_id> \
  --interval 2 --max-attempts 60 \
  --include card --output-file /tmp/link-card.json --format json
rm -f /tmp/link-card.json
```

## Step 5: Tell Vesta it is set up

Mention to your Vesta that stripe-pay is ready. Future requests like "renew my
domain" or "pay this invoice" will route through the Link CLI, and you will approve
each one in your Link app.

## Troubleshooting

- `auth status` says not authenticated: re-run Step 2.
- Approval push never arrives: confirm the Link app is installed and signed in on
  your device, and that notifications are enabled for it.
- `POLLING_TIMEOUT` on retrieve: you did not approve within the window (10 minutes).
  Start a fresh spend request.
- Spend refused: it exceeded a cap you set in Step 3. Raise the cap in the Link app
  or approve a smaller amount.
- Command not found: `npm i -g @stripe/link-cli`, or prefix calls with
  `npx -y @stripe/link-cli`.
