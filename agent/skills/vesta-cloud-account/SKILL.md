---
name: vesta-cloud-account
description: Owner asks about THIS box's Vesta hosting plan, billing, subscription, or renewal, or wants to upgrade/cancel/change card. Hosted (vesta.run) boxes only; not `onboard` (buying for someone else) or `stripe-pay` (third-party invoices).
---

# vesta-cloud-account, CLI: `vesta-cloud-account`

Lets you, the owner's own vesta, answer questions about **this** box's hosting
plan and help the owner manage their subscription, without ever holding their
billing credentials or the box's `api_key`.

## How it works (the trust model, read this)

You do **not** have a standing credential to the control plane. When you need
account info, the CLI asks **vestad** (running on this same box) to mint a
short-lived **server-identity token**. vestad signs it locally with the box's
`api_key` and hands it back. vestad never calls out; the token proves "I am
*this server*" to the control plane at `vesta.run`, scoped to this box's account
only. The `api_key` itself never reaches you.

So:

- **Reading the plan is free.** `vesta-cloud-account plan` just works on a hosted box.
- **Changes are facilitated, never automatic.** You cannot upgrade, cancel, or
  move money yourself. `vesta-cloud-account manage` returns a **Stripe-hosted link**; the
  owner opens it and confirms the change in Stripe's own UI. You *initiate*, the
  human *authorizes*.

This is deliberate. You are an AI, so you must never be able to silently change
someone's bill or cancel their account. The worst you can do is hand over a link.

## Trigger

Invoke when the **owner** asks about *their own* hosting:

- "what plan am I on", "how much am I paying", "when does it renew", "is my
  subscription active".
- "upgrade my plan", "cancel my account", "change my card", "manage my billing",
  "take me to my account".

## Skip

Self-hosted boxes have no plan (`vesta-cloud-account plan` says so). Buying a vesta for someone else is `onboard`; paying an external invoice or third party is `stripe-pay`.

## Commands

```
vesta-cloud-account plan          # this box's plan, price, status, renewal date (a read)
vesta-cloud-account manage        # a secure Stripe link to upgrade / cancel / change payment
vesta-cloud-account referral      # this box's referral code, credit earned, invites completed
vesta-cloud-account set-referral  # set/clear the code the onboard skill uses
```

Output is always JSON on stdout. Exit codes: 0 success, 2 surfaced `{error}`
(e.g. self-hosted box, no billing account yet), 3 control-plane/vestad
unreachable, 1 unexpected.

## How to use it in conversation

- **Plan questions:** run `vesta-cloud-account plan`, then tell them plainly the plan, the
  monthly price (`price_usd`), whether it is `active`, and when it renews
  (`renews_at`). Do not read raw JSON at them; summarize.
- **Any change (upgrade, cancel, card):** run `vesta-cloud-account manage`, give them the
  `url`, and say something like "here is your billing page, you can upgrade,
  change your card, or cancel from there." Then stop. **Do not claim** you
  upgraded or cancelled anything; you did not. They confirm it on that page.
- If `vesta-cloud-account plan` returns an error that this is not a hosted box, tell them
  they are self-hosted and there is no Vesta plan to manage.

## Referral code

If the owner asks about their referral code, invites, or earnings, run
`vesta-cloud-account referral` and read back `referral_code` and
`invites_completed` plainly; convert `referral_credit_cents` to a dollar figure
yourself rather than reading raw cents at them. If it comes back
`{"error": "not_hosted", ...}`, this box has no vesta-issued code; follow the
`message` it returns.

The `onboard` skill (the flow that invites someone new) needs this box's code to
credit the owner for a completed invite. Run
`vesta-cloud-account set-referral --code <code>` once so `onboard` picks it up
automatically from then on; there is no need to pass it every time. If the
owner's code is ever reissued or changes, re-run `set-referral` with the new one.
`vesta-cloud-account set-referral --clear` removes it (e.g. moving to a fresh code
or clearing a mistaken one).

## Honesty

Never imply you charged a card, changed a plan, or cancelled an account. You only
ever *read* the plan and *hand over a link*. If the owner asks "did it go
through", tell them to check the page or their email. You can re-run
`vesta-cloud-account plan` to read the current state, but you do not process the change.
