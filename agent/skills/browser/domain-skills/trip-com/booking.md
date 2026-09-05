# trip.com: booking a flight end to end

The `flights` skill treats trip.com as a primary booking path. This is the flow that works.

## The flow

1. **Search**: `https://uk.trip.com/flights/showfarefirst?dcity=<from>&acity=<to>&ddate=YYYY-MM-DD&triptype=ow&class=ys&quantity=<pax>&locale=en-GB&curr=EUR`
   Open it with `new_tab(url)` and read the DOM directly. `wait_for_load()` waits out its whole
   budget here and can still return with `document.body.innerText.length` at 0, while the page
   itself has rendered: `wait(3)` then read the DOM.
2. **Select the fare**: find the card containing the departure time, read the rect of its
   "Select this flight" button, and use a **real click** (`click_at_xy(x, y)`). A JS `.click()`
   here opens a popup the browser blocks silently: the tab appears and stays `about:blank`
   forever. See `interaction-skills/clicking.md`.
3. **Fare panel**, then `Continue`, and the passenger page opens in a NEW TAB. Focus it by URL match
   on `flights/passenger`.
4. **Passengers**. Names, gender, DOB, nationality. Three traps:
   - the DOB field expands into separate DD / MM / YYYY inputs once focused, and each part needs
     typing one character at a time (`type_text` per character, `wait(0.1)` between) or the value
     does not stick;
   - nationality must be picked from the dropdown list, not typed. Typed free text LOOKS accepted and
     is silently cleared on save;
   - each passenger needs **"Save & continue"** AND then a confirmation dialog ("Passenger
     information has been saved... check the spelling"). Until you confirm, the section reads
     "Not completed" and the page will not advance.
5. **Contact details**: pre-filled if signed in. **Check the phone country code**, which defaults to
   the site locale's rather than the one belonging to the number in the field.
6. **Email verification**: entering the contact address triggers a 6-digit code by email. Fetch it
   from the inbox and enter it.
7. **Next**, at which point the **"Duplicate Bookings"** dialog fires if the passengers hold another
   flight within 24h. It is invisible in `innerText` and eats every click on Next, which
   `document.elementFromPoint` on the button reports as a cover; "Continue booking" clears it.
8. **Seats**: "Skip seat selection", then "Next step".
9. **Add-ons**: decline insurance ("I don't want to protect my trip"), then "Next step", then a
   second last-chance insurance modal wants "Not now".
10. **Cashier** (`secure.trip.com/webapp/cashier/home`): saved cards are listed; the CVV field is not
    matchable by selector. Click its position, verify `document.activeElement` is an INPUT, then type
    into the focused element. **11-minute hold timer**; if it lapses the booking auto-cancels and a
    "Booking Cancelled" email follows.

## Baggage

The passenger page's baggage "Add" buttons may never open for a given fare. Buy bags from the
**airline** after ticketing instead, which is also cheaper than at the airport. Trip.com's own
bundled fare can still beat airline-bought bags, so compare before assuming the bare fare is cheaper.

## After payment

Payment success is NOT ticketing. The confirmation carrying the **airline PNR** arrives separately,
promised within 12 hours. Only the PNR lets the passenger manage the booking with the airline.

**The airline record's contact email is trip.com's ticketing desk, not the passenger's.** So on the
airline's own "manage my booking", looking up by PNR + email FAILS; use **PNR + surname**.

## Prices

Fares move within hours on the same search. Availability and ordering can be checked cheaply from
search results, but the price only exists in the cart at the moment of paying, and search-page base
fares differ from cart totals by more than the gap between two fares.
