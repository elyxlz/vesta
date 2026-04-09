#!/usr/bin/env bash
# Sync shared files from the main Vesta app into the dashboard.
# Run this during setup and whenever the main app updates.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_SRC="$SCRIPT_DIR/app/src"
REPO_APP_SRC="$SCRIPT_DIR/../../../app/src"

sync_from_local() {
    local app_root
    app_root="$(dirname "$1")"
    echo "Syncing from local app source: $1"
    cp "$app_root/components.json" "$SCRIPT_DIR/app/components.json"
    cp "$1/index.css" "$DASHBOARD_SRC/index.css"
    mkdir -p "$DASHBOARD_SRC/lib" "$DASHBOARD_SRC/hooks" "$DASHBOARD_SRC/components/ui"
    cp "$1/lib/utils.ts" "$DASHBOARD_SRC/lib/utils.ts"
    cp "$1/hooks/use-mobile.ts" "$DASHBOARD_SRC/hooks/use-mobile.ts"
    cp "$1/components/ui/"*.tsx "$DASHBOARD_SRC/components/ui/"
}

sync_from_git() {
    local repo_dir="$1"
    local ref
    # Use the current commit's tag if it has one (i.e. a release build), otherwise HEAD
    ref=$(git -C "$repo_dir" describe --exact-match --tags HEAD 2>/dev/null || echo "HEAD")

    echo "Syncing from git repo: $repo_dir (ref: $ref)"
    mkdir -p "$DASHBOARD_SRC/lib" "$DASHBOARD_SRC/hooks" "$DASHBOARD_SRC/components/ui"

    git -C "$repo_dir" show "$ref:app/components.json" > "$SCRIPT_DIR/app/components.json"
    git -C "$repo_dir" show "$ref:app/src/index.css" > "$DASHBOARD_SRC/index.css"
    git -C "$repo_dir" show "$ref:app/src/lib/utils.ts" > "$DASHBOARD_SRC/lib/utils.ts"
    git -C "$repo_dir" show "$ref:app/src/hooks/use-mobile.ts" > "$DASHBOARD_SRC/hooks/use-mobile.ts"

    git -C "$repo_dir" ls-tree --name-only "$ref:app/src/components/ui/" | while read -r file; do
        case "$file" in *.tsx)
            git -C "$repo_dir" show "$ref:app/src/components/ui/$file" > "$DASHBOARD_SRC/components/ui/$file"
        ;; esac
    done
}

if [ -d "$REPO_APP_SRC" ]; then
    sync_from_local "$(cd "$REPO_APP_SRC" && pwd)"
elif [ -d "$HOME/vesta/.git" ]; then
    sync_from_git "$HOME/vesta"
else
    echo "Error: no app source found (no local app/ dir and no git repo at ~/vesta/)" >&2
    exit 1
fi

# Patch index.css — transparent background for iframe embedding
# Remove bg-background from html/body (dashboard is embedded in iframe)
sed -i 's/bg-background //g; s/ bg-background//g; s/bg-background//g' "$DASHBOARD_SRC/index.css"
# Add transparent background to body
sed -i '/body {/{n;s|$|\n    background: transparent;|}' "$DASHBOARD_SRC/index.css"

# Tell Tailwind to scan gitignored synced files
sed -i '1s|^|@source "./components/ui";\n@source "./lib";\n@source "./hooks";\n|' "$DASHBOARD_SRC/index.css"

echo "Synced $(ls "$DASHBOARD_SRC/components/ui/" | wc -l) UI components"
echo "Done."
