---
hosts: thetrainline.com
---

# thetrainline.com, booking a UK train ticket (logged in)

Field-tested 2026-08-30, booking a same-day return with a saved account. The site is a React SPA;
the search widget's date/passenger controls are the fiddly part. Sequence that worked end-to-end:

## 1. Cookie + region walls (do first)
- A **OneTrust** consent dialog blocks all clicks until dismissed. Click **"Necessary only"** (a
  bare `.click()` on the target underneath fails with "covered by `.onetrust-pc-dark-filter`").
- If the account/session lands on the **US site** (`/en-us`, USD, "26 to 59 years of age", a banner
  "In the United Kingdom? Head over to our UK site"), switch to UK first: click the banner's
  **"Okay, let's go"** button. UK site prices in GBP and offers UK ticket types (Off-Peak Day Return
  etc.). Being signed in persists across the switch.

## 2. Sign in
Header "Sign in" opens a panel with Google/Facebook/Apple/**Email**. Fill the email/password inputs
by id (`header-signin-email`, `header-signin-password`) using the **native value setter + input/change
events** (React trick), then click the panel's own "Sign in" submit (find it inside
`document.getElementById('header-signin-password').closest('form')`). Verify success by checking the
account name appears in the header and no "incorrect/verify" error text is present.

## 3. The search form, synthetic events work for SOME fields, NOT the calendar
- **Stations**: `click_at_xy` the From/To combobox, `type_text("London Bridge")`, then click the
  first autocomplete option that appears. Works normally.
- **Journey type**: the `#return` radio responds to a plain `.click()`.
- **Calendar day cells + time selects DO NOT respond to synthetic `.value` / dispatched events** , 
  React reverts them instantly. Use **real input**:
  - Day cell: get its `getBoundingClientRect()` centre and click it by coordinate with
    `click_at_xy(x, y)`.
  - Hour/minute `<select>`: `click_at_xy(x, y)` to focus, then `press_key("ArrowUp"/"ArrowDown")` N times
    to step the value (a focused native select changes on arrow keys and fires a trusted change).
  - The **passenger age** confirm select (US-origin accounts demand "Select age") DOES accept the
    native-setter trick, set it to the option whose text is "<NN> years".
- **Passenger count can silently reset to 0** while fiddling → "Please add at least one passenger".
  Re-open the passenger panel and click the "Increase the number of adult passengers by 1" button.

## 4. Search submits into a NEW TAB
"Find cheap tickets" opens the results in a **new tab** (URL `/book/results?...`); the origin tab
stays on the homepage, which looks like a failed submit. Run `list_tabs()` and `switch_tab()` to
the `book/results` tab. Clicking the button several times spawns several duplicate results tabs, close
the extras.

## 5. Fares
Trainline pre-selects a sensible cheapest option. For a same-day round trip the flexible winner is
usually **"Super Off-Peak Day Return"** (return on any eligible off-peak train that day, not bound to
the searched time), the right-hand panel states the validity. Check the **Travel Insurance toggle is
OFF** before paying.

## 6. Checkout / payment
`/book/checkout` shows the trip, the cost breakdown (ticket + ~£0.69 booking fee), and payment. A
**saved card is pre-selected but still requires the 3-digit security code (CVV)** in a "Security code"
field, you must get that from the user; login alone will not complete payment. Then "Pay now".
Confirmation emails to the account address. Fare holds expire (~10-20 min), if the user is slow with
the CVV, the checkout may need re-searching.
