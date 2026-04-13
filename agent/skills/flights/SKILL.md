---
name: flights
description: Use this skill when the user asks about flights, plane tickets, airfare, travel deals, cheap flights, or wants to search for routes between cities/airports. Covers one-way, round-trip, and date-flexible searches. Books via Trip.com (primary, browser automation) or Duffel API (fallback).
---

# Flights

Search via Google Flights CLI. Book via **Trip.com** (primary) or **Duffel API** (fallback).

**When to use which:**
- **Trip.com** (primary): supports ALL airlines including Wizz Air and Ryanair. Browser automation via stealth Chromium. Use this by default.
- **Duffel** (fallback): API-based, faster and more reliable when the airline is supported. Does NOT support Wizz Air or Ryanair. Use for easyJet, Vueling, BA, and other GDS-connected airlines.

## User Preferences

Configure these based on your user's preferences:
- **Origin**: User's home city/airport(s)
- **Priority**: cheapest price (or as configured)
- **Class**: Economy (default)
- **Seat selection**: as preferred
- **Stops**: any (cheapest usually wins)

## Search Commands (Google Flights)

### Search flights on a specific date

```bash
# One-way, single origin
flights search JFK LAX 2026-04-15

# One-way, multiple origins (returns combined + sorted by price)
flights search JFK,EWR,LGA LAX 2026-04-15

# Round-trip
flights search JFK LAX 2026-05-01 --return-date 2026-05-05

# With filters
flights search JFK LAX 2026-04-20 --stops 0       # non-stop only
flights search JFK LAX 2026-04-20 --max-results 5
```

### Find cheapest dates in a date range

```bash
flights dates JFK LAX --from 2026-05-01 --to 2026-05-31
flights dates JFK,EWR LAX --from 2026-05-01 --to 2026-06-30
flights dates JFK LAX --from 2026-05-01 --to 2026-07-01 --round-trip --duration 5
```

### Find cheapest flights across multiple origins

The `cheapest` command searches all London airports by default. Adapt the `LONDON_AIRPORTS` list in `cli.py` to your user's home airports:

```bash
flights cheapest LAX
flights cheapest LAX --from 2026-05-01 --to 2026-07-31
flights cheapest LAX --round-trip --duration 4 --top 15
```

## Booking via Trip.com (Primary)

Browser automation via stealth Chromium. Supports ALL airlines including Wizz Air and Ryanair.

**IMPORTANT**: Always use a subagent for Trip.com booking. Browser work fills context fast. Launch a background subagent with all necessary details and let it run.

### Credentials

Store these in your password manager (e.g. Keeper):
- **Trip.com account**: your login credentials
- **Payment card**: your credit/debit card details
- **Passenger personal info**: passport number, DOB, nationality

### Trip.com Booking Flow (5 steps)

**Pre-flight: Launch stealth browser**
```bash
# Must use stealth mode for Cloudflare bypass
browser launch --stealth
```

**Step 1: Search**
- Navigate to `https://www.trip.com/flights/`
- Enter origin/destination airport codes, date, one-way
- Click search, wait for results to load
- Select the target flight from results (match by airline, time, price)
- Click through to booking page

**Step 2: Login (if needed)**
- Trip.com may prompt for login. Use email login
- It sends a 6-digit verification code to email
- Retrieve code from your email inbox
- Enter code to log in
- Login is sometimes dismissible - guest checkout also works but saved passengers won't be available

**Step 3: Passenger Details**
- If logged in, Trip.com shows saved passengers - select the correct passenger
- If manual entry, fill: given name, family name, gender (combobox - click to open, then click gender), DOB (3 separate fields: day/month/year), nationality (autocomplete - type and select), passport number, passport expiry
- Country code for phone: dropdown, scroll or type to find the correct code
- **Quirk**: gender field is a combobox, not a dropdown. Click the field, wait for options, click the value
- **Quirk**: DOB is 3 separate input fields (DD, MM, YYYY), not a single date picker
- **Quirk**: nationality is an autocomplete - type first few letters, wait, select from dropdown

**Step 4: Seat Selection + Extras**
- Skip seat selection (click "skip" or "no thanks" or equivalent)
- Skip all extras/add-ons (baggage, insurance, etc.) unless the user wants them

**Step 5: Payment**
- ~13 minute payment timer starts on the payment page
- If logged in and card is saved, it may pre-fill card details
- Otherwise enter: card number, expiry (MM/YY), CVC
- Click pay/confirm
- **3DS**: may trigger depending on card/airline. Check email for verification if needed
- Wait for confirmation page - capture booking number

### Post-Booking Checklist
1. Capture booking confirmation number from the confirmation page
2. Create calendar event (use flight time in local airport timezone)
3. Set 24h-before check-in reminder via `tasks remind`
4. Report booking details to user: airline, flight number, route, times, price, booking ref

### Trip.com Known Quirks
- **No CAPTCHAs** typically encountered during booking flow
- **Guest checkout works** but saved passengers not available without login
- **Card details persist** between bookings when logged in
- **Cloudflare**: requires `browser launch --stealth` to bypass
- **Payment timer**: ~13 minutes from entering payment page. Don't linger
- **Prices** depend on browser locale/IP

### Subagent Template for Trip.com Booking

When booking, launch a subagent with this info:
```
Book flight on Trip.com:
- Route: [ORIGIN] → [DESTINATION]
- Date: [DATE]
- Target flight: [AIRLINE] [FLIGHT_NUM] dep [TIME]
- Passenger: [NAME] (get details from Keeper or provide directly)
- Payment: [CARD] from Keeper or provided details
- Trip.com login: [CREDENTIALS from Keeper or config]
- Email verification codes: retrieve via email skill (inbox, Trip.com sender)
- Use `browser launch --stealth` first
- Follow the 5-step flow in the flights skill
- After booking: report confirmation number, create calendar event, set check-in reminder
```

---

## Booking via Duffel API (Fallback)

API-based booking. Faster and more reliable when the airline is supported. Use for easyJet, Vueling, BA, and other GDS-connected airlines. Does NOT support Wizz Air or Ryanair.

**Note**: Requires a funded Duffel balance before live bookings. Check balance before attempting.

### Search bookable offers

```bash
flights offer JFK LAX 2026-04-16
flights offer JFK LAX 2026-05-01 --return-date 2026-05-05
flights offer JFK LAX 2026-06-01 --passengers 2 --max-connections 0
```

### Book a flight

```bash
flights book <offer_id> --passenger-id <pas_id> --profile myprofile
```

### Other Duffel commands

```bash
flights orders                         # list orders
flights order <order_id>               # order details
flights cancel <order_id>              # cancel order
flights passenger list                 # list saved profiles
flights passenger show myprofile       # show profile
```

### Duffel Booking Flow

1. `flights offer [ORIGIN] [DEST] [DATE]` → get `offer_id` + `passenger_ids`
2. Review price, times, baggage
3. `flights book <offer_id> --passenger-id <pas_id> --profile myprofile`
4. Confirm → booking reference returned

**Important**: Offers expire (~30 min). Always search fresh before booking.

---

## Parameters Reference

| Flag | Description | Default |
|------|-------------|---------|
| `--stops` | ANY, 0 (non-stop), 1, 2 | ANY |
| `--cabin` | ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST | ECONOMY |
| `--sort` | CHEAPEST, DURATION, DEPARTURE_TIME, ARRIVAL_TIME | CHEAPEST |
| `--max-results` | Max results per origin | 10 (search), 20 (dates) |
| `--round-trip` | Search round-trip dates | false |
| `--duration` | Trip length in days (round-trip) | 3 |
| `--top` | Results for `cheapest` command | 10 |
| `--max-connections` | Max connections for Duffel offers (-1=any, 0=direct) | -1 |
| `--passengers` | Number of adult passengers for Duffel | 1 |

## Setup

Install with:
```bash
cd ~/vesta/skills/flights/cli && uv tool install --force --reinstall .
```

Duffel API token stored at `~/.config/duffel/token`. Passenger profiles at `~/.config/duffel/passengers.json`.

To configure your home airports for the `cheapest` command, edit `LONDON_AIRPORTS` in `cli/src/flights_cli/cli.py` - rename it to something like `HOME_AIRPORTS` and set your preferred departure airports.

## How It Works

**Search**: Uses the `fli` Python library which reverse-engineers the Google Flights API - sends direct POST requests to Google's `FlightsFrontendService` endpoint.

**Trip.com booking**: Browser automation via stealth Chromium (`browser` CLI). Navigates Trip.com as a real user - fills forms, handles login, completes payment.

**Duffel booking**: REST API v2. Acts as a flight consolidator. Supports easyJet, Vueling, BA, and many others. Ryanair and Wizz Air excluded from API.

## Gotchas

- **Google Flights destination must be single IATA code** - multi-origin works, multi-destination does NOT
- **Duffel offers expire** - typically ~30 minutes. Always search fresh before booking
- **Duffel does NOT support Wizz Air or Ryanair** - use Trip.com for these
- **Duffel balance**: must be funded before live bookings. Check balance before attempting
- Prices from Google Flights are in USD; Trip.com and Duffel prices depend on currency/locale
- **Trip.com browser sessions**: always use `--stealth` mode. Regular browser gets blocked by Cloudflare
- **Trip.com payment timer**: ~13 min. Don't browse around on the payment page

## Saved Profiles

Use `flights passenger save` to create reusable passenger profiles:

```bash
flights passenger save myprofile \
  --given-name "First" --family-name "Last" \
  --born-on YYYY-MM-DD --email user@example.com --phone +1234567890
```

Then reference with `--profile myprofile` when booking.
