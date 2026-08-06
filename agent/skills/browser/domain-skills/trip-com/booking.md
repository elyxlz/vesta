# trip.com — booking a flight end to end

Written 6 Aug 2026 after driving a real two-passenger booking to issued tickets. The `flights` skill
treats trip.com as a primary booking path and there was no recipe here, so the first attempt took
about two hours and the second about ten minutes. Everything below is from the second run.

## The flow

1. **Search**: `https://uk.trip.com/flights/showfarefirst?dcity=<from>&acity=<to>&ddate=YYYY-MM-DD&triptype=ow&class=ys&quantity=<pax>&locale=en-GB&curr=EUR`
   Navigate with **`"wait":"none"`**. With `wait=load` (and with plain `browser open`) the command
   returns clean and `document.body.innerText.length` is 0. See SKILL.md's blank-page paragraph.
2. **Select the fare**: find the card containing the departure time, take its
   `button "Select this flight"` ref, and use a **real click** (`browser click <ref>`). A JS
   `.click()` here opens a popup that Firefox blocks silently: the tab appears and stays
   `about:blank` forever. This one cost 40 minutes. See `interaction-skills/clicking.md`.
3. **Fare panel** → `Continue` → the passenger page opens in a NEW TAB. Focus it by URL match on
   `flights/passenger`.
4. **Passengers**. Names, gender, DOB, nationality. Three traps:
   - the DOB field expands into separate DD / MM / YYYY inputs once focused, and `browser type`
     needs `--slowly` or the value does not stick;
   - nationality must be picked from the dropdown list, not typed. Typed free text LOOKS accepted and
     is silently cleared on save;
   - each passenger needs **"Save & continue"** AND then a confirmation dialog ("Passenger
     information has been saved... check the spelling"). Until you confirm, the section reads
     "Not completed" and the page will not advance.
5. **Contact details**: pre-filled if signed in. **Check the phone country code**: it defaulted to
   +44 for an Italian +39 number.
6. **Email verification**: typing his address triggers a 6-digit code by email. Fetch it from the
   inbox and enter it. The code emails are yours, not an intrusion; do not relay them to the user.
7. **Next** → the **"Duplicate Bookings"** dialog fires if the passengers hold another flight within
   24h. It is invisible in `innerText` and eats every click on Next. `elementFromPoint` finds it;
   "Continue booking" clears it.
8. **Seats**: "Skip seat selection", then "Next step".
9. **Add-ons**: decline insurance ("I don't want to protect my trip"), then "Next step", then a
   second last-chance insurance modal wants "Not now".
10. **Cashier** (`secure.trip.com/webapp/cashier/home`): saved cards are listed; the CVV field is not
    matchable by selector. Click its position, verify `document.activeElement` is an INPUT, then type
    into the focused element. **11-minute hold timer**; if it lapses the booking auto-cancels and a
    "Booking Cancelled" email follows.

## Baggage

The passenger page's baggage "Add" buttons never opened for an Aeroitalia fare. Buy bags with the
**airline** after ticketing instead, which is also cheaper than the airport. Trip.com's own bundled
fare may still beat airline-bought bags: compare before assuming the bare fare is cheaper.

## After payment

Payment success is NOT ticketing. The confirmation with the **airline PNR** arrives separately,
promised within 12 hours and observed in 34 minutes. Only the PNR lets the passenger manage the
booking with the airline.

**The airline record's contact email is trip.com's ticketing desk, not the passenger's.** So on the
airline's own "manage my booking", looking up by PNR + email FAILS; use **PNR + surname**.

## Prices

The fare moved 213.96 -> 231.08 in three hours on the same search. Availability and ordering can be
checked cheaply from search results, but the price only exists in the cart at the moment of paying,
and search-page base fares differ from cart totals by more than the difference between two fares.
