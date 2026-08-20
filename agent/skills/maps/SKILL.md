---
name: maps
description: Find real places and their Google Maps links, get directions, and build multi-stop routes. Use when the user asks where to find something, wants a restaurant or shop nearby, asks how to get somewhere, or wants a route or day-out plan. Needs internet.
---

# Maps (CLI: maps)

Find places on Google Maps and hand the user a link that opens the exact place, or a route that
opens the whole trip. Every command prints JSON on stdout and takes durable Google ids, so a
place found in one turn is referred to later by its `place_id` or `cid`. The skill stores
nothing; keep your own working set in a trip file (below).

Set the user's locale and country so results and formatting match where they are:
`maps --locale it-IT --country it search ...`.

## Find places

```bash
maps search "frozen yogurt" --near "Alghero" --min-rating 4.4 --sort rating --limit 5
```

Each result carries `name`, `address`, `lat`/`lng`, `place_id`, `cid`, `rating`, `category`,
`website`, and a `links` block with a `place_url` (opens the exact place) and a `directions_url`.
Filter with `--min-rating`, `--category`, and `--sort rating`. `--near` takes an address or
`lat,lng`. `--radius-km` and `--sort distance` measure from `--near`, so they need it as
`lat,lng` (a coordinate, not a place name).

Send the user the `place_url` for a single pick. It opens the exact place on the web and the
Maps app on a phone.

## Directions

```bash
maps directions 40.5748,8.317 --mode walking          # to a place, from live location
maps directions 40.5748,8.317 --from 40.559,8.319 --mode transit
```

`--mode` is `driving`, `transit`, `walking`, or `bicycling`. Omit `--from` so the phone uses the
user's current location.

## A multi-stop route

```bash
maps route --mode walking --stops '[
  {"name":"Gelateria oops!","lat":40.5748,"lng":8.317,"place_id":"ChIJw6O4C_nx3BIRXWUjEmxzB3s"},
  {"name":"ReGelato","lat":40.5579,"lng":8.3138,"place_id":"ChIJ15JUBN7x3BIRed4zU5H7kw8"}
]'
```

Pass each stop's `place_id` (from a prior `search`) so the stops render as named places, not
dropped pins. One `route_url` comes back that opens the whole ordered route.

## Other

```bash
maps geocode "Piazza Porta Terra, Alghero"   # address -> coords + place_id
maps doctor                                   # health check: is the search RPC responding
```

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
