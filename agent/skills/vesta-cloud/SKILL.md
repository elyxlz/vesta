---
name: vesta-cloud
description: THIS box's Vesta Cloud account. Use to check whether it has one and read its environment (`whoami`, the account/plan/setup signal other skills key off), get a server-identity token to call the control plane (`token`), or answer the owner about their hosting plan, billing, renewal, upgrade/cancel/card, and referral code. Not `onboard` (buying for someone else); not `stripe-pay` (third-party invoices).
---

# vesta-cloud, CLI: `vesta-cloud`

The single authority for **this** box's Vesta Cloud account: whether it has one, a
credential to act as it against the control plane, its plan, and its referral code.
Install the `vesta-cloud` command once from [SETUP.md](SETUP.md). Output is always JSON
on stdout. Exit codes: 0 success, 2 surfaced `{error}` (no account / no billing yet),
3 control-plane or vestad unreachable, 1 unexpected.

## `whoami`: does this box have an account?

```bash
vesta-cloud whoami
# { "account": true, "plan": "membership", "status": "active",
#   "renews_at": "2026-09-01T00:00:00.000Z", "price_usd": 48.0,
#   "managed_infra": true, "control_url": "https://vesta.run/api", "agent_name": "ada" }
```

`account` is the fact to branch on: `true` means this box is paired to a Vesta Cloud
account the control plane recognizes (read `status` for whether it is `active` versus,
say, `suspended`); `false` means it has none yet, and `reason` says why. It is the
signal other skills read to choose a cloud path over a self-managed one, so consult
`whoami` rather than reading any environment variable. `managed_infra` is the narrower, separate fact that this VM is Vesta-operated;
a box can hold an account without it. `account:false` exits 0 (a valid answer); a real
vestad/control-plane outage exits 3.

## `token`: a credential for calling the control plane

```bash
vesta-cloud token
# { "token": "<server-identity JWT>", "control_url": "https://vesta.run/api", "expires_in": 600 }
```

Hands another skill a short-lived server-identity token plus the control-plane URL, so
it calls the control plane as this server without minting its own. One token is general:
it authenticates any server-scoped route (`/account`, integrations, ...). Errors when the
box has no account. This is how every skill that needs to reach the control plane as the
server gets its credential.

## The trust model (read this)

You hold **no** standing credential to the control plane. Each command asks **vestad**
(on this same box) to mint a short-lived server-identity token; vestad signs it locally
with the box's `api_key` and hands it back. vestad makes no network call, and the
`api_key` never reaches you. The token proves "I am *this server*", expires in minutes,
and is scoped to this box's account.

So reading is free (`whoami`, `plan`), and changes are only ever **facilitated**:
`manage` returns a Stripe-hosted link the owner opens and confirms in Stripe's own UI.

## Plan and billing

```
vesta-cloud plan     # plan, price (price_usd), status, renews_at
vesta-cloud manage   # a Stripe-hosted link to upgrade / cancel / change payment
```

- **Plan questions:** run `plan`, then tell the owner plainly the plan, the monthly
  price (`price_usd`), whether it is `active`, and when it renews (`renews_at`).
  Summarize; do not read raw JSON at them.
- **Any change (upgrade, cancel, card):** run `manage`, give the owner the `url`, and
  say something like "here is your billing page, you can upgrade, change your card, or
  cancel from there." Then stop.

## Referral code

```
vesta-cloud referral               # referral_code, referral_credit_cents, invites_completed
vesta-cloud set-referral --code X  # persist the code `onboard` sends on a completed invite
vesta-cloud set-referral --clear   # remove the stored code
```

Read `referral_code` and `invites_completed` back plainly; convert
`referral_credit_cents` to a dollar figure yourself rather than reading raw cents.

The `onboard` skill needs this box's code to credit the owner for a completed invite.
Run `set-referral --code <code>` once so `onboard` picks it up from then on; re-run it
if the owner's code changes. If `referral` returns `{"error": "not_hosted", ...}`, this
box has no vesta-issued code; follow the `message` it returns.

## Honesty

Never imply you charged a card, changed a plan, or cancelled an account. You only ever
*read* the plan and *hand over a link*. If the owner asks "did it go through", tell them
to check the page or their email; re-run `plan` to read the current state.
