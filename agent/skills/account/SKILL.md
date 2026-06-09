---
name: account
description: Use when the OWNER asks about their Vesta hosting plan, billing, subscription, or account. Triggers like "what plan am I on", "how much am I paying", "when does it renew", "upgrade my plan", "cancel my account", "change my card", "manage my billing". Reads the plan directly, and for any change (upgrade, cancel, payment) hands back a secure link the owner opens to confirm. Hosted (vesta.run) boxes only; a self-hosted box has no plan. NOT for buying a new vesta for someone else (that is `onboard`), and NOT for paying a third-party invoice (that is `stripe-pay`).
---

# account, CLI: `account`

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

- **Reading the plan is free.** `account plan` just works on a hosted box.
- **Changes are facilitated, never automatic.** You cannot upgrade, cancel, or
  move money yourself. `account manage` returns a **Stripe-hosted link**; the
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

- A **self-hosted** box (no `managed` flag, no plan). `account plan` will say so.
- Buying a vesta for **someone else**, that is `onboard`.
- Paying an external invoice or a third party, that is `stripe-pay`.

## Commands

```
account plan      # this box's plan, price, status, renewal date (a read)
account manage    # a secure Stripe link to upgrade / cancel / change payment
```

Output is always JSON on stdout. Exit codes: 0 success, 2 surfaced `{error}`
(e.g. self-hosted box, no billing account yet), 3 control-plane/vestad
unreachable, 1 unexpected.

## How to use it in conversation

- **Plan questions:** run `account plan`, then tell them plainly the plan, the
  monthly price (`price_usd`), whether it is `active`, and when it renews
  (`renews_at`). Do not read raw JSON at them; summarize.
- **Any change (upgrade, cancel, card):** run `account manage`, give them the
  `url`, and say something like "here is your billing page, you can upgrade,
  change your card, or cancel from there." Then stop. **Do not claim** you
  upgraded or cancelled anything; you did not. They confirm it on that page.
- If `account plan` returns an error that this is not a hosted box, tell them
  they are self-hosted and there is no Vesta plan to manage.

## Honesty

Never imply you charged a card, changed a plan, or cancelled an account. You only
ever *read* the plan and *hand over a link*. If the owner asks "did it go
through", tell them to check the page or their email. You can re-run
`account plan` to read the current state, but you do not process the change.
