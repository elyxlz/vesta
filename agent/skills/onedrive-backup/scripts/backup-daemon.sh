#!/bin/bash
# OneDrive backup daemon — syncs agent files to OneDrive every hour.
#
# Usage: screen -dmS onedrive-backup bash ~/vesta/skills/onedrive-backup/scripts/backup-daemon.sh
#
# Requires:
#   - microsoft skill authenticated with Files.ReadWrite scope
#   - Python environment with msal installed (uses microsoft skill's venv)

PYTHON="${ONEDRIVE_BACKUP_PYTHON:-/root/.local/share/uv/tools/microsoft/bin/python}"
SCRIPT="$(dirname "$0")/onedrive-sync.py"
INTERVAL="${ONEDRIVE_BACKUP_INTERVAL:-3600}"

while true; do
    echo "[$(date -u +"%Y-%m-%d %H:%M UTC")] starting OneDrive sync..."
    $PYTHON "$SCRIPT" 2>&1
    echo "[$(date -u +"%Y-%m-%d %H:%M UTC")] sync complete, sleeping ${INTERVAL}s"
    sleep "$INTERVAL"
done
