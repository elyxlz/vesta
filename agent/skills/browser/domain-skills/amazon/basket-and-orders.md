# Amazon: basket, delivery dates, order history, tracking

Field-tested on amazon.co.uk (Sep 2026) in a signed-in chromium session. Selectors are the same
family on amazon.com.

## Adding to the basket

A coordinate click on the add-to-basket button can silently do nothing (the basket count stays at
0 and nothing errors), especially after a scroll. Clicking the button element from JS works
reliably here, because it submits an ordinary form:

```python
goto_url("https://www.amazon.co.uk/dp/<ASIN>")
wait(3)
js("document.querySelector('#add-to-cart-button').click()")
wait(4)
print(js("(document.querySelector('#nav-cart-count')||{}).innerText"))  # must go up by 1
```

Always confirm each add with `#nav-cart-count`, never with the click's return value. A listing with
several variants may need the variant chosen first (the URL gains `?th=1`).

## Reading the basket

The per-row `data-asin` selectors on the basket page are not stable; the robust read is the page
text:

```python
goto_url("https://www.amazon.co.uk/gp/cart/view.html")
wait(5)
t = js("document.body.innerText.replace(/\\s+/g,' ')")
i = t.find("Subtotal")
print(t[i : i + 160])  # e.g. "Subtotal (3 items): £42.00"
```

The summary can show "Gift card: - £50.00" and a lower "Amount to pay" that are a credit card
sign-up advert (the Amazon Barclaycard offer, "if approved"), not a balance the account holds. Read
the text just before "Subtotal" for "if approved", and confirm any real balance at
`https://www.amazon.co.uk/gc/balance` ("Your Gift Card Balance") before quoting a discounted total.

"Your Amazon Basket is empty" in the text means the adds did not stick. Items listed under "Saved
for later" are not in the basket and will not be bought at checkout.

## Delivery dates

Read `#mir-layout-DELIVERY_BLOCK` on the product page. The dates a signed-in Prime account sees
differ from a signed-out visitor's (signed-out shows the free standard date only). Quote dates only
from the signed-in page, and note "order within N hrs" countdowns: the date is only valid inside
that window.

## Order history and tracking

```python
goto_url("https://www.amazon.co.uk/gp/css/order-history")
wait(6)
cards = js(
    "JSON.stringify([...document.querySelectorAll('.order-card, .js-order-card')].map(c=>c.innerText.replace(/\\s+/g,' ').slice(0,400)))"
)
```

Each card's text carries the order date, total, status ("Arriving today", "Delivered today") and
items. For live tracking, follow the card's "Track package" link and read the page text for
"Arriving", "Out for delivery" and "N stops away".
