# Maps skill setup

## Prerequisites

- Python 3.12+
- uv (https://docs.astral.sh/uv/)
- Internet access

## Install the CLI

```bash
uv tool install --editable ~/agent/skills/maps/cli
```

Verify:

```bash
maps --help
maps doctor
```

`maps doctor` probes every RPC once against a fixed landmark (Buckingham Palace) and reports
each check: `search`, `place`, `directions`, `transit` (a timed departure), and `reverse`. It
exits 0 when all pass and 1 with the failing checks named otherwise.

## How it works

The skill replays Google Maps' own public web endpoints over plain HTTP (no browser, no account,
no API key). It reads the country and language from `--locale`/`--country`, so pass the user's
own values for results and formatting that match where they are.

`search`, `show`, and `itinerary` print a human table by default and structured JSON with
`--json` / `--json-pretty`; the other commands always print JSON.
`search` and `show` record each place's identity (name, coordinates, ids) in a small cache at
`~/.gmaps/places.json`, so `directions --to <cid>` resolves with no extra call. The cache holds
only stable identity and is safe to delete anytime; set `GMAPS_CACHE_DIR` to relocate it.

## When results stop coming back

Google changes its internal request and response shapes from time to time. A failing `maps
doctor` check names the `pb` template to re-capture: `search` -> `search_pb.txt`, `place` ->
`place_pb.txt`, `directions` -> `directions_pb.txt`, `transit` -> `transit_pb.txt`, `reverse` ->
`reverse_pb.txt`, all under `cli/src/gmaps_cli/`. Read a fresh `pb` from the matching live Maps
request and update the template (the header of `pb.py` describes the exact steps). If a
template is current but fields come back null, the response shape moved instead: re-pin the
positions in `proto.py`.
