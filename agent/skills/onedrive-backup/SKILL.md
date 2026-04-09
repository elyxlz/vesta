---
name: onedrive-backup
description: Use this skill to back up agent files (memory, data, skills, config) to OneDrive via Microsoft Graph API. Provides failsafe recovery independent of container backups, with full version history via OneDrive's built-in file versioning.
---

# OneDrive Backup

Syncs agent files to OneDrive using the Microsoft Graph API, providing a second layer of backup independent of vestad's container-level snapshots.

**Why two backups?** Vestad backs up the entire Docker container as an image. This skill backs up the agent's "brain" — memory, data, dreamer logs, skill customizations — as individual files to OneDrive. Each file retains full version history via OneDrive, so you can restore any previous version of any file (e.g. roll back MEMORY.md to yesterday's version).

**Setup**: See [SETUP.md](SETUP.md) — requires Microsoft auth with `Files.ReadWrite` scope.

## How it works

```
~/vesta/ ──(Graph API upload)──> OneDrive/{agent}/
```

- Uploads files directly from the agent directory to OneDrive via Microsoft Graph API
- Files larger than 3.75MB use chunked upload sessions (Graph API requirement: chunks must be multiples of 320KB)
- Failed uploads retry up to 3 times
- Excludes `.venv`, `__pycache__`, `.git`, `node_modules`, and other build artifacts

## Usage

```bash
# One-off sync
/path/to/microsoft/python ~/vesta/skills/onedrive-backup/scripts/onedrive-sync.py

# Run as hourly daemon
screen -dmS onedrive-backup bash ~/vesta/skills/onedrive-backup/scripts/backup-daemon.sh
```

## Recovery scenarios

### Restore a single file
1. Go to OneDrive web → navigate to the agent backup folder
2. Right-click the file → "Version history"
3. Select the version to restore → "Restore" or "Download"
4. Copy back into the container

### Restore after container failure
If vestad container restore fails or is unavailable:
1. Download the entire backup folder from OneDrive
2. Recreate the container
3. Copy the backup files into `~/vesta/`

### Continuous version history
Every sync overwrites files in OneDrive, but OneDrive retains version history for each file. This means:
- Every hourly sync creates a new version of changed files
- You can browse and restore any historical version
- No manual snapshots needed — it's automatic

## Recommended setup

Add to `restart.md` for automatic operation:

**Hourly daemon** (in services list):
```
screen -dmS onedrive-backup bash ~/vesta/skills/onedrive-backup/scripts/backup-daemon.sh
```

**Post-restart one-off** (after services are up and agent is responsive):
```
screen -dmS onedrive-oneoff bash -c 'PYTHON_PATH /path/to/scripts/onedrive-sync.py 2>&1 | tee ~/vesta/logs/onedrive-sync.log'
```

This ensures the last known-good state is captured to OneDrive immediately after every clean restart, before any new changes are made.

## Configuration

Edit variables at the top of `scripts/onedrive-sync.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `ONEDRIVE_FOLDER` | `Okami/okami-vesta` | OneDrive destination folder |
| `CHUNK_SIZE` | 3932160 (3.75MB) | Upload chunk size (must be multiple of 320KB) |
| `EXCLUDE` | `.venv`, `__pycache__`, `.git`, etc. | Directories/files to skip |

## Notes
- Requires the `microsoft` skill to be authenticated with `Files.ReadWrite` scope
- Token refresh is handled automatically via MSAL cache
- If token acquisition fails, re-authenticate: `microsoft auth add --account user@example.com`
- Large binary files (models, databases) will upload but may be slow — consider adding them to `EXCLUDE` if not needed for recovery
