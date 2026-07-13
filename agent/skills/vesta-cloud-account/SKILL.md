---
name: vesta-cloud-account
description: Owner asks about THIS box's Vesta hosting plan, billing, subscription, or renewal, or wants to upgrade/cancel/change card. Hosted (vesta.run) boxes only; not `onboard` (buying for someone else) or `stripe-pay` (third-party invoices).
---

# vesta-cloud-account, CLI: `vesta-cloud-account`

Answer questions about **this** box's hosting plan and help the owner manage their subscription, without ever holding their billing credentials or the box's `api_key`.

## Trust model

You have no standing credential to the control plane. When you need account info, the CLI asks **vestad** (on this box) to mint a short-lived **server-identity token**; vestad signs it locally with the box's `api_key` and returns it. vestad never calls out; the token proves "I am *this server*" to `vesta.run`, scoped to this box's account only. The `api_key` never reaches you.

- **Reading the plan is free** on a hosted box.
- **Changes are facilitated, never automatic.** You cannot upgrade, cancel, or move money. `manage` returns a **Stripe-hosted link**; the owner opens it and confirms in Stripe's own UI. You *initiate*, the human *authorizes*. An AI must never silently change someone's bill.

## Trigger

Owner asks about *their own* hosting:
- "what plan am I on", "how much am I paying", "when does it renew", "is my subscription active".
- "upgrade my plan", "cancel my account", "change my card", "manage my billing".

## Skip

Self-hosted boxes have no plan (`plan` says so). Buying a vesta for someone else is `onboard`; paying an external/third-party invoice is `stripe-pay`.

## Commands

```
vesta-cloud-account plan          # this box's plan, price, status, renewal date (a read)
vesta-cloud-account manage        # a secure Stripe link to upgrade / cancel / change payment
vesta-cloud-account referral      # this box's referral code, credit earned, invites completed
vesta-cloud-account set-referral  # set/clear the code the onboard skill uses
```

Output is always JSON on stdout. Exit codes: 0 success, 2 surfaced `{error}` (e.g. self-hosted, no billing account yet), 3 control-plane/vestad unreachable, 1 unexpected.

## In conversation

- **Plan questions:** run `plan`, then summarize the plan, `price_usd`, whether it is `active`, and `renews_at`. Don't read raw JSON at them.
- **Any change (upgrade, cancel, card):** run `manage`, give them the `url` ("here is your billing page, you can upgrade, change your card, or cancel from there"), then stop. **Do not claim** you upgraded or cancelled anything; they confirm on that page.
- If `plan` errors that this is not a hosted box, tell them they are self-hosted and there is no plan to manage.

## Referral code

If the owner asks about their referral code, invites, or earnings, run `referral` and read back `referral_code` and `invites_completed`; convert `referral_credit_cents` to dollars yourself. If it returns `{"error": "not_hosted", ...}`, this box has no code; follow the `message`.

The `onboard` skill needs this box's code to credit the owner for a completed invite. Run `vesta-cloud-account set-referral --code <code>` once so `onboard` picks it up automatically. Re-run if the code is reissued. `set-referral --clear` removes it.

## Honesty

Never imply you charged a card, changed a plan, or cancelled an account: you only *read* the plan and *hand over a link*. If asked "did it go through", tell them to check the page or their email (or re-run `plan`); you do not process the change.
