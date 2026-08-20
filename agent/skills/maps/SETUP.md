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

`maps doctor` runs a known-good query and reports whether the search RPC is responding.

## How it works

The skill replays Google Maps' own public web endpoints over plain HTTP (no browser, no account,
no API key). It reads the country and language from `--locale`/`--country`, so pass the user's
own values for results and formatting that match where they are.

Commands print a human table by default and structured JSON with `--json` / `--json-pretty`.
`search` and `show` record each place's identity (name, coordinates, ids) in a small cache at
`~/.gmaps/places.json`, so `directions --to <cid>` resolves with no extra call. The cache holds
only stable identity and is safe to delete anytime; set `GMAPS_CACHE_DIR` to relocate it.

## When results stop coming back

Google changes its internal response shape from time to time. If `maps doctor` reports a drift
(a known-good query returns nothing), the search `pb` template needs re-capturing: read a fresh
`pb` from a live Maps search request and update `cli/src/gmaps_cli/search_pb.txt` (the header of
`pb.py` describes the exact steps).
