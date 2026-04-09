# OneDrive Backup — Setup

## Prerequisites

1. **Microsoft skill** must be installed and authenticated
2. **Files.ReadWrite scope** must be granted — if your microsoft auth only has Mail/Calendar scopes, re-authorize:
   ```bash
   microsoft auth add --account user@example.com
   ```
   When prompted, ensure `Files.ReadWrite` is included in the consent screen.

## Configuration

Edit `scripts/onedrive-sync.py` and set:

- `ONEDRIVE_FOLDER`: Where to store backups in OneDrive (default: `Okami/okami-vesta`)
- `EXCLUDE`: Files/directories to skip (default includes `.venv`, `__pycache__`, `.git`, `node_modules`)

## Test

Run a one-off sync to verify:

```bash
/path/to/microsoft/python ~/vesta/skills/onedrive-backup/scripts/onedrive-sync.py
```

You should see:
```
[OneDrive sync] starting — /root/vesta → OneDrive/Okami/okami-vesta/
[OneDrive sync] token OK
[OneDrive sync] 50 files uploaded...
...
[OneDrive sync] done — N uploaded, N skipped, 0 errors
```

## Add to restart.md

Once working, add the daemon to your services list in `~/vesta/prompts/restart.md`:

```
screen -dmS onedrive-backup bash ~/vesta/skills/onedrive-backup/scripts/backup-daemon.sh
```
