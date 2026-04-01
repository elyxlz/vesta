#!/bin/bash
# okami backup script — runs periodically, pushes MEMORY.md + data/ to GitHub

BACKUP_DIR="/root/vesta/backup-repo"
TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M UTC")

# Sync files
cp /root/vesta/MEMORY.md "$BACKUP_DIR/MEMORY.md"
rm -rf "$BACKUP_DIR/data" && cp -r /root/vesta/data/ "$BACKUP_DIR/data/"

cd "$BACKUP_DIR"

# Pull first to avoid conflicts (in case of manual edits)
git pull origin main --rebase --quiet 2>/dev/null || true

# Stage and commit
git add -A
if git diff --cached --quiet; then
    echo "[$TIMESTAMP] nothing to backup"
    exit 0
fi

git commit -m "backup: $TIMESTAMP" --quiet
git push origin HEAD:main --quiet

echo "[$TIMESTAMP] backup pushed"
