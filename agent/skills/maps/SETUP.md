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

## When results stop coming back

Google changes its internal response shape from time to time. If `maps doctor` reports a drift
(a known-good query returns nothing), the response templates need re-capturing. The dev capture
harness lives under `cli/tools/`.
