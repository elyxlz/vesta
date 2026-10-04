# Court booking availability (Padel Mates, MATCHi, Playtomic)

All three platforms answer plain `curl` with a desktop UA for availability, so check free courts
without a browser. Verified against public clubs (Sep 2026).

## Rules for every platform

- **A "no slots" answer needs a control.** Before telling the user nothing is free, run the same
  query for another day (or another club on the same platform) and confirm that one returns slots.
  An empty result from a wrong id, a wrong sport, or a changed endpoint looks exactly like a full
  day.
- **Mind the timezone.** Two of the three return UTC times; convert to the club's local time before
  quoting.
- **Booking needs the user's own account** on that platform. Sign-up usually sends a verification
  email whose link expires within minutes, so have the user (or the email skill) ready to open it
  straight away.

## Padel Mates (padelmates.se)

Club page: `https://padelmates.se/club/<club_id>` (a JS app; curl gets an empty shell). The id is
the 32-hex string in that URL.

```bash
D=<YYYY-MM-DD>; Z=<club timezone, e.g. Europe/Stockholm>
S=$(TZ=$Z date -d "$D" +%s)000
E=$(TZ=$Z date -d "$D + 1 day" +%s)000
curl -s -A "Mozilla/5.0" -H "Origin: https://padelmates.se" \
  "https://fastapi-production-fargate.padelmates.io/player/player_booking/all_courts_slot_prices_v3?club_id=<club_id>&start_datetime=$S&end_datetime=$E&lang=en"
```

`start_datetime` and `end_datetime` are epoch milliseconds. The response's `allSlots[]` entries
carry `courtName`, `duration` (minutes), `price`, `startTimestamp` (ms epoch) and
`reservedIntersection`. Convert `startTimestamp` to local time; the `startTime` string is UTC. A
slot with `reservedIntersection: true` overlaps an existing booking. The same start time appears
once per bookable duration (60, 90, 120).

**Caveat: `allSlots` can omit free start times that the website's grid shows.** Treat it as a lower
bound: before telling the user a time is unavailable, open the club page in the browser and check
the grid.

## MATCHi (matchi.se)

The facility page `https://www.matchi.se/facilities/<slug>` contains `facilityId: "<n>"` in its
script, and the sport picker's `<option value="5">` is Padel (read the options for other sports).

```bash
curl -s -A "Mozilla/5.0" \
  "https://www.matchi.se/book/schedule?wl=&facilityId=<n>&date=<YYYY-MM-DD>&sport=5&week=&year="
```

This returns an HTML grid. Each `td.slot` has class `free`, `red` (booked) or `not-available`, and
a `title` like `Available<br>Court name<br> 14:45 - 15:30` in the venue's local time. Only `free`
is bookable. Some venues sell 45-minute slots only, so a request for "an hour" may need two
consecutive slots.

Booking (logged-in session): the price is not in the schedule grid; clicking a `free` slot opens a
"Verify" dialog with the court, time and price. Its `Next` submit goes to `checkout.matchi.com`
(card fields in third-party iframes; no saved card means the user must supply one). Nothing is
held or reserved at the dialog or the checkout step: the slot is the user's only once payment
succeeds and a "Booking confirmation" email arrives from `no-reply@matchi.se`.

## Playtomic (playtomic.com)

The club page `https://playtomic.com/clubs/<slug>` embeds the club's `tenant_id` (a UUID). Several
tenant ids can appear in the page (nearby clubs); the club's own is the first, and sits next to
`tenant_name` and `"slug":"<slug>"`, so confirm the slug matches. The same block carries the club's
`timezone`, `opening_hours`, and `resources` (court `resourceId` to `name`).

```bash
curl -s -A "Mozilla/5.0" \
  "https://playtomic.com/api/clubs/availability?tenant_id=<tenant_id>&date=<YYYY-MM-DD>&sport_id=PADEL"
```

The response is a list, one entry per court: `resource_id`, `start_date`, and `slots[]` of
`{start_time, duration, price}`. `start_time` is UTC (an earliest slot an hour before the listed
opening time during BST is the tell); convert with the page's `timezone`. Map `resource_id` to a
court name through `resources`. The older `/api/v1/availability` path returns 404.
