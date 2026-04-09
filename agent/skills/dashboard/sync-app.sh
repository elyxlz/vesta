#!/usr/bin/env bash
# Sync shared files from the main Vesta app into the dashboard.
# Run this during setup and whenever the main app updates.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_SRC="$SCRIPT_DIR/app/src"
UPSTREAM_REPO="$HOME/vesta"

if [ ! -d "$UPSTREAM_REPO/.git" ]; then
    echo "Error: no git repo found at $UPSTREAM_REPO" >&2
    exit 1
fi

# Use VESTA_VERSION from vestad env (set automatically — branch for dev, tag for releases)
ref="${VESTA_VERSION:-HEAD}"

# Fetch only the ref we need
git -C "$UPSTREAM_REPO" fetch --depth=1 origin "$ref" 2>/dev/null || true

# Skip if already synced to this ref
last_sync_file="$SCRIPT_DIR/app/.last-sync"
if [ -f "$last_sync_file" ] && [ "$(cat "$last_sync_file")" = "$ref" ]; then
    echo "Already synced to $ref, skipping."
    exit 0
fi

echo "Syncing from git repo: $UPSTREAM_REPO (ref: $ref)"
mkdir -p "$DASHBOARD_SRC/lib" "$DASHBOARD_SRC/hooks" "$DASHBOARD_SRC/components/ui"

git -C "$UPSTREAM_REPO" show "$ref:app/components.json" > "$SCRIPT_DIR/app/components.json"
git -C "$UPSTREAM_REPO" show "$ref:app/src/index.css" > "$DASHBOARD_SRC/index.css"
git -C "$UPSTREAM_REPO" show "$ref:app/src/lib/utils.ts" > "$DASHBOARD_SRC/lib/utils.ts"
git -C "$UPSTREAM_REPO" show "$ref:app/src/hooks/use-mobile.ts" > "$DASHBOARD_SRC/hooks/use-mobile.ts"

git -C "$UPSTREAM_REPO" ls-tree --name-only "$ref:app/src/components/ui/" | while read -r file; do
    case "$file" in *.tsx)
        git -C "$UPSTREAM_REPO" show "$ref:app/src/components/ui/$file" > "$DASHBOARD_SRC/components/ui/$file"
    ;; esac
done

# Patch index.css — transparent background for iframe embedding
sed -i 's/bg-background //g; s/ bg-background//g; s/bg-background//g' "$DASHBOARD_SRC/index.css"
sed -i '/body {/{n;s|$|\n    background: transparent;|}' "$DASHBOARD_SRC/index.css"

# Tell Tailwind to scan gitignored synced files
sed -i '1s|^|@source "./components/ui";\n@source "./lib";\n@source "./hooks";\n|' "$DASHBOARD_SRC/index.css"

# Record the synced ref so we can skip next time
echo "$ref" > "$last_sync_file"

echo "Synced $(ls "$DASHBOARD_SRC/components/ui/" | wc -l) UI components"
echo "Done."
