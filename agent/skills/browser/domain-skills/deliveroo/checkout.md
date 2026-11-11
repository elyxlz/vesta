# Deliveroo UK: login, basket, scheduling, checkout

Field-tested on deliveroo.co.uk (Oct 2026) in a signed-in chromium session.

## Login

A login from a fresh browser profile sends a 6-digit OTP to the account's phone and email. Click
`#otp-use-password` to sign in with the password instead.

## Restaurant menu

- **Adding an item**: each card has its own stepper, `button[aria-label="Increase quantity"]`
  inside the card. The first add may open a modal; confirm with its "Add for £x" button.
- **"Go to checkout"** can open a "Fancy anything else?" upsell modal with its own checkout
  button; click that one to continue.

## Order value cap

**"Your order can't be placed right now, try again in a few minutes" at payment can be a
per-restaurant single-order value cap, not an outage.** The payment page never says so. The cap
only surfaces as a modal ("Sorry, your order just became too large... can't exceed £X") when
clicking the "Deliver in ..." row on the menu page. Check it before a large order and split into
orders under the cap.

## Scheduled delivery

Click the "Scheduled" row, find the `input[type=radio]` whose `name` is the slot text
(e.g. `"21:30 - 22:00"`), click its parent, then Confirm. Verify "Today HH:MM - HH:MM" now shows
under the delivery options. A slot that will not apply may be full; try the next one.

## Payment

- The payment method reverts to the account default on reload. Re-select it every time: the
  "Change" after "Pay with", click the label "Ending NNNN", then "Use this payment method".
- The final button reads "Pay now £x £y".
- Success is the URL `/orders/<id>/status`; confirm the order on `/orders`.
- **Alcohol** in the basket prompts "Confirm your date of birth" (`input[name=dateOfBirth]`,
  `YYYY-MM-DD`). It is checked against ID on delivery.

## Grocery stores

- **Two products can share the IDENTICAL title at different prices, and one is alcohol free.**
  The difference shows only in the item's Details tab ("Alcohol Free" / ABV). Before adding any
  item with a same-title sibling, open Details and read the ABV; a suspiciously cheap duplicate
  is the tell.
- Items default to "Substitute if unavailable". To prevent a swap, click the item in the basket,
  choose "Remove if unavailable", then Update.

## Order help

Order help opens inside an iframe served from `order-help-web-client.roocdn.com`. Drive it through
the iframe target, not the top page.
