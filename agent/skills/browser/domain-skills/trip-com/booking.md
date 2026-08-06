# trip.com: booking a flight end to end

The `flights` skill treats trip.com as a primary booking path. This is the flow that works.

## The flow

1. **Search**: `https://uk.trip.com/flights/showfarefirst?dcity=<from>&acity=<to>&ddate=YYYY-MM-DD&triptype=ow&class=ys&quantity=<pax>&locale=en-GB&curr=EUR`
   Navigate with **`"wait":"none"`**. With `wait=load`, and with plain `browser open`, the command
   returns clean and `document.body.innerText.length` is 0. See SKILL.md's blank-page paragraph.
2. **Select the fare**: find the card containing the departure time, take its
   `button "Select this flight"` ref, and use a **real click** (`browser click <ref>`). A JS
   `.click()` here opens a popup that Firefox blocks silently: the tab appears and stays
   `about:blank` forever. See `interaction-skills/clicking.md`.
3. **Fare panel**, then `Continue`, and the passenger page opens in a NEW TAB. Focus it by URL match
   on `flights/passenger`.
4. **Passengers**. Names, gender, DOB, nationality. Three traps:
   - the DOB field expands into separate DD / MM / YYYY inputs once focused, and `browser type`
     needs `--slowly` or the value does not stick;
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
   flight within 24h. It is invisible in `innerText` and eats every click on Next, which `browser
   click` reports as a cover; "Continue booking" clears it.
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
