# iCloud Skill Setup

## Prerequisites

* Python 3.11+
* uv (https://docs.astral.sh/uv/)
* Apple ID + password
* At least one trusted phone number on the Apple ID account (for SMS 2FA)

## Step 1: Install the CLI

```bash
uv tool install --force --reinstall ~/agent/skills/icloud/cli
```

## Step 2: Provide credentials

Pick whichever option fits your setup. The CLI tries them in order.

### Option A: `~/.icloud/credentials.json` (recommended, no extra deps)

```bash
mkdir -p ~/.icloud
cat > ~/.icloud/credentials.json <<JSON
{"account": "you@example.com", "password": "your-apple-id-password"}
JSON
chmod 600 ~/.icloud/credentials.json
```

### Option B: Keeper record titled `Apple ID` or `iCloud`

If the keeper skill is configured, the CLI searches Keeper for a record whose
title contains `Apple ID` or `iCloud` and uses its `login` + `password` fields.
No record UID is hardcoded. Add a record with the appropriate title and the CLI
will find it.

### Option C: env var (account only)

`ICLOUD_APPLE_ID=you@example.com` overrides the email; the password still has
to come from option A or B.

## Step 3: First login

```bash
icloud auth login                                          # uses defaults
icloud auth login --apple-id you@example.com               # override email
icloud auth login --phone-suffix 1234                      # pick a trusted phone
```

Behavior:

1. Reads creds, calls Apple's auth endpoint, triggers SMS to your trusted
   phone (the first one Apple returns, or the one matching `--phone-suffix`).
2. Spawns a background worker that polls `~/.icloud/code.txt` for the 6-digit code.
3. Returns once the worker reaches `phase=awaiting_code` (~5s) so the agent can prompt the user.

Then submit the code:

```bash
icloud auth verify --code 123456
```

On success, `~/.icloud/state.json` shows `phase: trusted` and cookies are persisted in `~/.icloud/cookies/`.

## Step 4: Verify

```bash
icloud auth status
icloud albums --shared
```

`auth status` exits 0 only when `is_trusted_session: true`.

## Cookies and re-auth

Apple invalidates the trusted session roughly every 30 days. When that happens, `auth status` reports `is_trusted_session: false`; just rerun `auth login` and `auth verify`.

The cookie jar lives in `~/.icloud/cookies/` and contains one file per Apple ID. To completely reset:

```bash
rm -rf ~/.icloud/cookies ~/.icloud/state.json
```

## Reference

* Working scratch scripts that informed this skill: `/tmp/icloud_sms_italy.py` (SMS 2FA), `/tmp/icloud_list_albums.py` (album listing).
* Auth state files (all under `~/.icloud/`):
  * `config.json` last-used account + phone id
  * `state.json` current login phase and message
  * `cookies/` pyicloud cookie + session jar
  * `code.txt` written by `auth verify`, consumed by the worker
  * `worker.log` background worker stdout/stderr
