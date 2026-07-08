---
name: stripe-pay
description: Use when the user wants Vesta to pay a merchant on their behalf (buy something, renew a domain, settle an invoice at a card-taking site). Drives Stripe's Link CLI; the user approves each spend in their Link app. Requires one-time setup (see SETUP.md).
---

# stripe-pay - CLI: `link-cli` (Stripe Link for Agents)

Lets Vesta spend on the user's behalf through Stripe's **Link for Agents**, using
the official `@stripe/link-cli`. Vesta never holds the user's real card: each
purchase mints a single-use virtual card (or a one-time Machine Payment Protocol
token) that Stripe releases **only after the user approves the spend in their Link
app**. Vesta hands that ephemeral credential to the merchant's checkout, then
reports the outcome.

This skill is a thin guide over `link-cli`. It does not wrap it in Python: drive
`link-cli` directly. It is self-describing, so when in doubt ask it, not this file:

```bash
link-cli --llms-full                 # every command, one page
link-cli spend-request create --schema   # exact flags + shapes for one command
```

If `link-cli` is not on PATH, run it via `npx -y @stripe/link-cli <args>` (Node is
present in the container). Setup installs it globally so plain `link-cli` works.

## Trigger / Skip

Use when the user asks Vesta to buy or pay for something at a merchant ("order me
X", "renew my domain", "pay this invoice", "grab those tickets"). Not for P2P
sends (Link for Agents is merchant-only) and not for read-only expense logging
(use `enable-banking`). Paying an external invoice or third party is this skill;
buying a vesta for someone else is `onboard`; this box's own hosting bill is
`vesta-cloud-account`.

If setup has not run, `link-cli auth status` reports unauthenticated: stop, point
the user at SETUP.md, and do not attempt a spend.

## Before spending: check auth

```bash
link-cli auth status
```

If it reports not authenticated, the user must complete SETUP.md first. Do not try
to authenticate them mid-task: `auth login` needs the user to approve a device in
their Link account, which is a setup step, not a per-charge step.

## Making a purchase

The flow is: create a spend request, let Stripe push it to the user's Link app for
approval, poll until it reaches a terminal state, then use the released credential.

### 1. (Optional) pick a payment method

```bash
link-cli payment-methods list --format json
```

Use a returned `id` as `--payment-method-id`. Omit it to let Link use the user's
default.

### 2. Create the spend request and request approval

```bash
link-cli spend-request create \
  --merchant-name "Acme Domains" \
  --merchant-url "https://acme.example" \
  --context "Renewing example.com for 1 year on the user's behalf; the user asked Vesta to keep the domain from lapsing this week." \
  --amount 2499 \
  --line-item "name:example.com renewal (1yr),unit_amount:2499,quantity:1" \
  --total "type:total,display_text:Total,amount:2499" \
  --request-approval \
  --format json
```

- **`--amount` is in the currency's minor units (cents).** `2499` = $24.99, `100`
  = $1.00. This is Stripe's convention; do not pass major units.
- **`--context` must be at least 100 characters** and honestly describe the
  purchase. The user reads it when approving, so write it for them, not for logs.
- `--request-approval` sends a **push notification to the user's Link app**. Note
  the returned spend request id (`lsrq_...`) and follow any `_next` hint in the
  output.
- Add `--credential-type shared_payment_token` only for merchants that accept
  Machine Payment Protocol (see MPP below); the default mints a virtual card.
- Add `--test` to rehearse in Stripe test mode (uses card 4242 4242 4242 4242, no
  real money).

**Tell the user, in the conversation you are already in, that you have requested
approval and they need to approve it in their Link app.** Approval happens there,
not by replying to Vesta. They have 10 minutes.

### 3. Poll until approved, then retrieve the credential

```bash
link-cli spend-request retrieve <lsrq_id> \
  --interval 2 --max-attempts 300 \
  --include card \
  --output-file /tmp/link-card.json --format json
```

`retrieve` with `--interval`/`--max-attempts` **blocks until the request reaches a
terminal state** (approved, denied, expired, or canceled) and exits non-zero with
`POLLING_TIMEOUT` if it never leaves pending. On approval it writes the unmasked
card to the `--output-file` (mode 0600) while stdout stays redacted. The file
contains `number`, `cvc`, `exp_month`, `exp_year`, `billing_address`
(name/line1/line2/city/state/postal_code/country), and `valid_until` (a Unix
timestamp; credentials are good for 12 hours).

If the request was denied, expired, or timed out, the card file is not written:
tell the user it was not approved and stop. Do not retry a denied request.

### 4. Use the card, then clean up

Hand the card details to the browser or checkout flow that completes the purchase.
When done, delete the file: it is the one place the raw number touches disk.

```bash
rm -f /tmp/link-card.json
```

### 5. Report the outcome

```bash
link-cli report --domain acme.example --outcome success --spend-request-id <lsrq_id>
```

Use `--outcome blocked` (with a `--tag`, e.g. `captcha`, `payment_declined`) or
`--outcome abandoned` when checkout does not complete, so Stripe and the user have
an accurate trail.

## Machine Payment Protocol (MPP) merchants

Some merchants take a programmatic payment token instead of a card form. Create the
spend request with `--credential-type shared_payment_token`, get it approved and
retrieved as above, then:

```bash
link-cli mpp pay https://merchant.example/api/pay \
  --spend-request-id <lsrq_id> \
  --method POST --data '{"amount":2499}'
```

The shared payment token is one-time-use. If the merchant handed you an MPP
challenge string, `link-cli mpp decode --challenge '...'` extracts what you need.

## Guardrails

- **Never bypass approval.** Every spend goes through a Link-approved spend request.
  There is no auto-approve and no way for Vesta to approve on the user's behalf,
  and that is the point.
- **One purchase, one spend request.** Do not fan out parallel spend requests for a
  single purchase; Link caps concurrent requests and it confuses the approval feed.
- **Do not persist card numbers.** Use `--output-file` (0600), pass the card
  straight to checkout, then delete it. Never write a card into memory, a task, or
  a log.
- **Caps live in Link, not here.** The user sets per-charge / daily / monthly caps
  in their Link app. A spend over a cap is refused by Stripe; surface that to the
  user rather than working around it. Per-request ceiling is $5,000.
- **Amounts are minor units.** `--amount` is always cents (or the currency's
  smallest unit). Re-read step 2 before every charge.

## Files

`link-cli` owns its own auth credentials (default `~/.link`, overridable via
`LINK_AUTH_FILE`, or supplied by `LINK_ACCESS_TOKEN` / `LINK_REFRESH_TOKEN`). This
skill stores nothing of its own.
