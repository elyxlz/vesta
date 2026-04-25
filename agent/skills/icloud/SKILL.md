---
name: icloud
description: iCloud Photos: list and download shared albums via pyicloud. SMS 2FA to a trusted phone.
---

# iCloud Photos

Read access to iCloud Photos. Designed around shared-album download.

## Setup

See [SETUP.md](SETUP.md). Apple ID + password come from `~/.icloud/credentials.json` or a Keeper record titled `Apple ID` / `iCloud`. Cookies live in `~/.icloud/cookies/`. The session has to be re-trusted every ~30 days via SMS 2FA.

## Authentication flow

Apple requires SMS 2FA on every new device. The login worker runs in the background, triggers an SMS to your trusted phone number (the first one Apple returns, or the one matching `--phone-suffix`), and waits for `auth verify`.

```bash
icloud auth login                     # spawns background worker, sends SMS
                                      # state goes to ~/.icloud/state.json
                                      # phase=awaiting_code when SMS sent
icloud auth login --apple-id you@example.com --phone-suffix 1234
                                      # explicit Apple ID + last digits of
                                      # the trusted phone to receive SMS on
icloud auth verify --code 123456      # submit the 6-digit code
icloud auth status                    # check trust state
```

The agent should:

1. Run `icloud auth login`. If the JSON shows `phase: awaiting_code`, ask the user for the 6-digit code.
2. Run `icloud auth verify --code <code>`. On success, `phase` becomes `trusted`.
3. Proceed with `albums` / `download` / `sync-shared`.

If `auth status` reports `is_trusted_session: true`, skip the login flow.

## Commands

### List albums

```bash
icloud albums                         # both shared + owned
icloud albums --shared                # only shared streams
icloud albums --owned                 # only owned/smart albums
```

Each entry has `name`, `id`, `kind` (shared|owned), `photo_count`, and (for shared) `sharing_type`.

### Download an album

```bash
icloud download "Crete" --to ~/Pictures/Crete
icloud download 44A15AF2-446C-4B3B-B0FB-A619244CAE62 --to ~/dl/crete
icloud download "Toscana" --to ~/dl/toscana --quality medium --no-include-videos
```

Flags:

* `--to PATH` (required) destination directory; created if missing.
* `--include-videos / --no-include-videos` default on.
* `--quality original|medium|small` default `original`.

Existing files with matching size are skipped, so the command is idempotent.

### Sync every shared album

```bash
icloud sync-shared --to ~/Pictures/iCloud-Shared
```

Creates one subfolder per shared album. Same `--quality` and `--include-videos` flags as `download`.

## Album resolution

`icloud download <album>` accepts either the album id (UUID for shared, smart-name for owned) or the album name. Shared albums win on tie; owned albums are searched second. Names with emoji work as long as they are passed verbatim (quote them).

## Notes

* Photos are streamed straight from iCloud's CDN through the authenticated session; no full-album buffer in memory.
* Live Photos: the still image is downloaded; the paired video is fetched only when `--include-videos` is on (it shows up as a separate `.MOV` next to the `.HEIC`).
* `pyicloud` returns HEIC for originals on iPhone-sourced albums. Use `--quality medium` for JPEG.
* If the SMS step fails (phone not in trusted list), check `~/.icloud/state.json` for the candidate list under `candidates`.
* Cookies are cached under `~/.icloud/cookies/`. Apple invalidates them roughly every 30 days; re-run `icloud auth login` when `auth status` reports `is_trusted_session: false`.

## Installed via

`uv tool install ~/agent/skills/icloud/cli`
