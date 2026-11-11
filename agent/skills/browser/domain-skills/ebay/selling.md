# eBay: Seller Tasks (Sign-in, Revise, Payouts)

Field-tested against ebay.co.uk on 2026-10-10 in standard Chromium (no stealth). Other eBay
sites share the paths; swap the domain.

## Sign-in

1. `https://signin.ebay.co.uk` may first show an hCaptcha "I am human" wall. That is a human
   step: run `browser handover start` and let the user tick it.
2. Then: fill `#userid`, click `#signin-continue-btn`, fill `#pass`, click `#sgnBt`.
3. SMS step-up: click the "Text me" button. The code goes into 6 single-digit inputs: focus the
   first input and `type_text(code)`; focus auto-advances through the rest.
4. A "Trust this browser?" page follows. Click Confirm; it skips the code on later sign-ins.

Payments pages ask for the password again: a sign-in page with `pp=pass` in the URL and a
`#pass` field.

## Seller Hub and messages

| Page | URL |
|------|-----|
| Active listings (views, watchers, offers columns) | `https://www.ebay.co.uk/sh/lst/active` |
| Messages | `https://mesg.ebay.co.uk/mesgweb/ViewMessages/0` |

## Revise a listing

`https://www.ebay.co.uk/sl/list?mode=ReviseItem&itemId=<id>` redirects to
`/lstng?draftId=...&mode=ReviseItem`.

| Field | Selector |
|-------|----------|
| Price | `input[name=price]` |
| Best Offer toggle | `bestOfferEnabled` |
| Auto-decline below | `input[name=autoDeclineAmount]` |
| Description (mirror) | `textarea[name=description]` |

- The submit button's text is **"Save"**; there is no "Revise it" button. Success shows
  "Your listing has been revised".
- For a private seller, the item page then shows the price including the buyer protection fee,
  so it reads higher than the price entered. That is expected, not a failed save.
- Photo count: read "N out of 25 photos" on the revise page. The item page carousel
  (`.ux-image-carousel-item`) repeats images, so counting its nodes overstates the photos.

### Editing the description

The editor is the iframe `#se-rte-frame__summary`, mirrored into `textarea[name=description]`.
Setting the iframe's `innerHTML` or the textarea's value from JS does **not** persist. What works:

1. Inside the iframe document, find the target text with a `TreeWalker`, build a `Range` over
   it, and make that range the selection.
2. `type_text(replacement)` to overwrite the selection with real key input.
3. Move focus to another field (e.g. `input[name=price]`) so the editor syncs into the textarea.
4. Read `textarea[name=description]` and confirm it carries the new text, then click Save.

Verify by reopening the revise page, not the item page: the description iframe served from
`itm.ebaydesc.com` can lag behind the save.

## Payouts (bank account)

- Wallet: `https://ppcapp.ebay.co.uk/myppc/wallet/list`
- Add-payout flow directly:
  `https://ficapp.ebay.co.uk/iof?from=wallet&createflowparam=%7B%22subFlow%22%3A%22WALLET%22%2C%22flow%22%3A%22PAYOUT%22%7D`

Steps: "Add payout method", choose the Bank account radio (`input[name=payment-option]`),
Continue, then the "Add your bank account" page.

- The bank account name must exactly match the eBay account holder's name. A business account
  in a company name is refused for a private eBay account.
- The bank is linked through an open-banking widget (a `paywithmybank.com` iframe) that needs
  the user's own bank login. Hand it over with `browser handover start --minutes 60`; 30 minutes
  ran out mid-flow in testing.
- Success sends two emails: "Your payout method has been updated" and a direct-debit
  confirmation, because the same account is also charged for selling costs.

## Sold-items research

```
https://www.ebay.co.uk/sch/i.html?_nkw=<query>&LH_Sold=1&LH_Complete=1
```

Works signed in. Cards are `li.s-card` (older layout `li.s-item`), price in `.s-card__price`,
sold date in the card caption. Broad queries match unrelated items, so filter results by keyword
in the title before quoting a price range.
