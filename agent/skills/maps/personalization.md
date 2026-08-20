# Using places and travel the way your user likes them

Before a place or travel task, read `~/agent/data/place-preferences.md`. It holds what you have
learned about this user: the restaurants and shops they like, the exact branches they mean, and
how they prefer to travel each route. Apply it. When you learn something new, or the user
corrects you, update the file. You own it; keep it short, specific, and current.

If the file does not exist, create it with these sections:

```markdown
# Place & travel preferences

## Food & restaurants
## Specific places (the exact branch they mean)
## Home & work
## Travel & commutes
## Avoid / dislikes
```

Record a place as a `name` plus its `place_id`, never a name alone. A name is ambiguous; a
`place_id` is one exact place. Store the user's home and work here too, so "near me" has a
fallback and commutes have fixed endpoints.

## Finding restaurants your user likes

Learn their taste from what they say ("I love proper Neapolitan pizza"), from which option they
pick, from places they return to, and from constraints (vegetarian, no spicy, under GBP 20).
Record the pattern: cuisines, price band, must-avoids, named favorites with `place_id`.

Apply the pattern in the search, then rank by fit:

```bash
# preferences: loves izakaya, min rating 4.4, near the office
maps search "izakaya" --near <office lat,lng> --min-rating 4.4 --sort rating
```

Drop known dislikes from the results. Lead with a known favorite if one is near. When unsure,
offer two or three that fit the pattern and say why each fits, then record which one they pick,
because that choice is the strongest signal you get.

## Finding a shop without confusing it for another

A shop name is not one place. "Tesco" is hundreds of branches; "my pharmacy" is one exact
branch. Resolve to the branch, never the name.

- For a recurring place ("my gym", "the usual Tesco"), read its `place_id` from
  `place-preferences.md` and use that, so you always act on the right branch. Its `place_url`
  is `https://maps.google.com/?cid=<cid>` for the exact place you stored.
- For a new lookup, do not assume the first result is the one they mean. The fields that tell
  results apart are address and distance from the user. Show those and confirm, or match against
  what you know (their area, their usual branch). When they confirm a branch they will ask about
  again, record it with its `place_id`.

## User-preferred travel

Learn how the user travels each route, not just in general. A commute may be the Underground
while an airport run is a car. Record it per route: home to work = transit; airport = car.

Set the mode you know they prefer:

```bash
# preferences: home->work = transit; home and work stored with their place objects
maps directions --to '<work place json>' --from '<home place json>' --mode transit --steps
```

The link sets the travel mode; it cannot force one specific line or road. So when the user
prefers a line ("the Victoria line") or a road, set the mode, read the `--steps` result (it
carries the duration and the line), and tell them the trip. For a commute at a set time, add
`--depart HH:MM` or `--arrive HH:MM` with the user's `--tz` so the duration reflects the
schedule. Record the preference so you apply it next time.

## Two rules that prevent the common mistakes

1. For any place the user has named before, use its stored `place_id`, not a fresh name search.
   This is how you avoid sending them to the wrong branch.
2. When you are not sure you have the right place or route, confirm with the distinguishing
   fields (address, distance) before you act, and record what their answer teaches you.
