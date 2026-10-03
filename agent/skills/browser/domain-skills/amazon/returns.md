# Amazon: returning an item

Field-tested on amazon.co.uk (Sep 2026) in a signed-in chromium session. The flow is four steps
(reason, condition, refund, method) and then one irreversible confirm.

Never click "CONFIRM YOUR RETURN" without the user's explicit go on the return method and date.

## Starting the return

Open the order details page and follow its "Return items" link:

```python
goto_url("https://www.amazon.co.uk/gp/your-account/order-details?orderID=<orderId>")
wait(4)
print(js("[...document.querySelectorAll('a')].filter(a=>a.href.includes('/spr/returns/cart')).map(a=>a.href)"))
```

The link has the form `/spr/returns/cart?itemId=<itemId>&orderId=<orderId>`. Keep the `itemId`:
the reason form below is keyed on it.

## Step 1: reason and comments

The reason is a native `<select>` whose option texts include "Description on website was not
accurate" and similar. Set it by value from JS and dispatch a bubbling `change`:

```python
js("""(() => {
  const s = [...document.querySelectorAll('select')].find(s =>
    [...s.options].some(o => o.text.includes('Description on website was not accurate')));
  const o = [...s.options].find(o => o.text.includes('Description on website was not accurate'));
  s.value = o.value;
  s.dispatchEvent(new Event('change', {bubbles: true}));
  return o.value;
})()""")
```

Picking a reason reveals a REQUIRED comments textarea. The page holds several textareas at once:
hidden ones for every other reason, plus a visible nameless one that belongs to the Rufus
shopping-assistant panel. `querySelector('textarea')` hits Rufus. Select the right one by name: it
contains the `itemId` and the reason code, e.g.
`...RO_AMZ-PG-BAD-DESC-AC_REQUIRED_WHAT_IS_WRONG_WITH_WEBSITE`.

Real keystrokes (`click_at_xy` then `type_text`) do not register in this field. Set it through the
native value setter and dispatch `input` and `change`:

```python
js("""(() => {
  const t = document.querySelector("textarea[name*='<itemId>'][name*='BAD-DESC']");
  const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
  set.call(t, 'The item does not match the listing description.');
  t.dispatchEvent(new Event('input', {bubbles: true}));
  t.dispatchEvent(new Event('change', {bubbles: true}));
  return t.name;
})()""")
```

Confirm it took: the "N characters remaining" counter under the field drops.

The yellow Continue button sits in the right-hand column at the top of the page, not under the
form. Scroll to the top, read its coordinates with `getBoundingClientRect()`, and use a real
`click_at_xy`.

## Step 2: condition questions

"Skip this step" is offered, and the page states the answers do not affect the right to return.

## Step 3: refund

Radio options: "Refund to your Amazon account balance" (faster) or "Refund to your <card>" (5 to 7
business days after the item is received). Pick the original payment method unless the user said
otherwise.

## Step 4: return method and date

Options vary by item and address. Seen on amazon.co.uk: ASDA drop-off (box, no label needed), Evri
drop-off (needs a printer and a box), and Amazon Pickup (the driver brings the label; an adult
21+ must be present; original packaging; an 11:00 to 21:00 slot; date tiles for roughly the next 8
days). Relay the options and their conditions to the user before choosing.

Pickup date tiles sit in a horizontal scroller. After clicking one, take a `capture_screenshot()`
and check that the chosen tile is highlighted before going on.

## Confirming

"CONFIRM YOUR RETURN" is the irreversible click. On success the URL becomes
`/spr/returns/confirmation/<uuid>` and the body text holds "Your return request is confirmed", the
pickup or drop-off date, and the refund timeline:

```python
t = js("document.body.innerText.replace(/\\s+/g,' ')")
print("/spr/returns/confirmation/" in js("location.href"), "Your return request is confirmed" in t)
```

A confirmation email follows from `return@amazon.co.uk`.
