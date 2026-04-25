# Exa Skill Setup

## Prerequisites

- Python 3.11+
- uv (https://docs.astral.sh/uv/)
- An Exa API key from https://dashboard.exa.ai/api-keys

## Step 1: Install the CLI

```bash
uv tool install --force --reinstall ~/agent/skills/exa/cli
```

## Step 2: Configure the API key

Any of these work; the CLI checks them in this order:

1. **`EXA_API_KEY` env var** (good for CI / one-off):
   ```bash
   export EXA_API_KEY="exa_..."
   ```

2. **`~/.exa/config.json`** (recommended for local use):
   ```bash
   exa auth setup --api-key exa_xxx
   ```
   This writes `{"api_key": "exa_..."}` to `~/.exa/config.json` with mode 600.

3. **Keeper record named "Exa API"** (if you already use the keeper skill):
   Create a Keeper record titled `Exa API` with a custom field `api_key`.
   The CLI will fall back to `keeper get "Exa API"` automatically.

## Step 3: Verify

```bash
exa auth status
exa search "hello world" --num 1
```

## Pricing

Exa charges per request. See https://exa.ai/pricing. Every response includes `costDollars`. Deep research (`exa research`) can cost a few cents to dollars per task depending on model and scope. Always mention cost to the user for long-running research.
