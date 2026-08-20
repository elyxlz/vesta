---
name: maps
description: Find real places and their Google Maps links, get directions, and build multi-stop routes. Use when the user asks where to find something, wants a restaurant or shop nearby, asks how to get somewhere, or wants a route or day-out plan. Needs internet.
---

# Maps (CLI: maps)

Find places on Google Maps and hand the user a link that opens the exact place, or a route that
opens the whole trip. You refer to a place across commands by its `cid` (a durable Google id).

`search`, `show`, and `itinerary` print a human table by default; add `--json` (or
`--json-pretty`) to read a result programmatically. The other commands always print JSON. Set
the user's locale and country so results and formatting match where they are:
`maps --locale it-IT --country it search ...`.

## Find places

```bash
maps search "frozen yogurt" --near "Alghero" --min-rating 4.4 --sort rating --json
```

The `--json` output is a list of results, each with `name`, `address`, `lat`/`lng`, `place_id`,
`cid`, `ftid`, `rating`, `category`, `website`, and a `links` block (`place_url` opens the exact
place; `directions_url` is a ready directions link). The table shows each result's `cid`, which
you pass to `show` or `directions`. Filter with `--min-rating`, `--category`, and `--sort rating`.
`--near` takes an address or `lat,lng`; `--radius-km` and `--sort distance` measure from `--near`,
so they need it as `lat,lng` (a coordinate, not a place name).

Send the user the `place_url` for a single pick. It opens the exact place on the web and the
Maps app on a phone.

## Full detail for one place

```bash
maps show 8865181299500082525          # the cid from a search result
```

Returns name, address, coordinates, place_id, rating, category, phone, website, today's hours,
and photo links for one place. Use it to answer "what's the number", "is it far", "what does it
look like" about a place you already found.

## Directions

First `search` for the place ("Heathrow Terminal 5 station"), pick the right result, and pass
its `cid` to `--to`. The link is addressed by that place's `place_id`, so it opens the exact
place, never a dropped pin and never the wrong branch.

```bash
maps directions --to 8865181299500082525 --mode walking
```

You refer to the place by `cid` alone: `search` and `show` remember each place's identity, so
`directions` resolves the `cid` with no extra call. `--mode` is `driving`, `transit`, `walking`,
or `bicycling`. Omit `--from` so the phone uses the user's current location; pass `--from <cid>`
to fix the start. Add `--steps` (with `--from`) to also fetch the trip: duration, distance, and
turn-by-turn steps. Tell the user the duration; send the `directions_url`.

For transit, `--depart HH:MM` or `--arrive HH:MM` (with `--from` and `--tz`) fetch the route for
that time, so the duration reflects the schedule, and the returned `directions_url` opens Maps
with the time preset. Pass the user's timezone as `--tz` (e.g. `Europe/Rome`).

```bash
maps directions --to <colosseum cid> --from <termini cid> --mode transit --arrive 09:00 --tz Europe/Rome
```

## A multi-stop route

```bash
maps route --mode walking --stops '[
  {"name":"Gelateria oops!","lat":40.5748,"lng":8.317,"place_id":"ChIJw6O4C_nx3BIRXWUjEmxzB3s"},
  {"name":"ReGelato","lat":40.5579,"lng":8.3138,"place_id":"ChIJ15JUBN7x3BIRed4zU5H7kw8"}
]'
```

Pass each stop's `place_id` (from a prior `search`) so the stops render as named places, not
dropped pins. One `route_url` comes back that opens the whole ordered route.

## A scheduled day plan

```bash
maps itinerary --stops 8865181299500082525,1122517333730123385 --mode walking --start 21:00 --dwell 20
```

Give it the stops' cids in order. It returns each stop with an arrive and leave time (from
`--start` and `--dwell` minutes per stop), the travel time for each leg, a total, and one
`route_url` that opens the whole day. Add `--optimize` to reorder the stops for less travel. Save
the plan and its `route_url` in the trip file (below).

## Other

```bash
maps geocode "Piazza Porta Terra, Alghero"   # address -> coords + place_id
maps reverse 41.9028,12.4964                  # coords -> Google's label for the point
maps doctor                                   # health check: is the search RPC responding
```

`reverse` returns a street address when the point is near a building, otherwise a Plus Code for
open ground.

## Keep track of a plan in a trip file

For anything with more than one stop, keep a trip file at `~/agent/data/trips/<slug>.md` as your
plan of record. Record candidate places with their `place_id`, the chosen ordered stops, the
route link, and your decisions. Read it back on the next turn to remember what you picked, then
build the route from those ids. Keep it short and current. The user can open it too.

```markdown
# Trip: Alghero evening (2026-08-19)
Goal: late gelato crawl on foot, open past 22:00.

## Candidates
- [4.7] Gelateria oops! -- Via delle Baleari 53 -- place_id: ChIJw6O4C_nx3BIRXWUjEmxzB3s
- [4.5] ReGelato -- Via Carlo Alberto 65 -- place_id: ChIJ15JUBN7x3BIRed4zU5H7kw8

## Chosen (walking)
1. oops!  2. ReGelato

## Route
<route_url>
```

## Fit it to the user

Read [personalization.md](personalization.md) before a place or travel task: it covers finding
the restaurants the user likes, resolving the exact shop they mean, and their preferred travel
per route. Read [presentation.md](presentation.md) for how to show places in chat.

You may use maps on your own initiative when it helps, for example directions to the user's next
calendar event or a nudge to leave in time, composing with the tasks and reminders skills.

## Setup

See [SETUP.md](SETUP.md).
