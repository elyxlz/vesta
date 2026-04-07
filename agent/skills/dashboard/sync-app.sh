#!/usr/bin/env bash
# Sync shared files from the main Vesta app into the dashboard.
# Run this during setup and whenever the main app updates.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_SRC="$SCRIPT_DIR/app/src"
REPO_APP_SRC="$SCRIPT_DIR/../../../app/src"

if [ -d "$REPO_APP_SRC" ]; then
    APP_SRC="$(cd "$REPO_APP_SRC" && pwd)"
    echo "Syncing from local app source: $APP_SRC"

    cp "$APP_SRC/styles/globals.css" "$DASHBOARD_SRC/globals.css"

    mkdir -p "$DASHBOARD_SRC/lib"
    cp "$APP_SRC/lib/utils.ts" "$DASHBOARD_SRC/lib/utils.ts"

    mkdir -p "$DASHBOARD_SRC/hooks"
    cp "$APP_SRC/hooks/use-mobile.ts" "$DASHBOARD_SRC/hooks/use-mobile.ts"

    mkdir -p "$DASHBOARD_SRC/components/ui"
    cp "$APP_SRC/components/ui/"*.tsx "$DASHBOARD_SRC/components/ui/"
else
    # Inside agent container — fetch from GitHub
    echo "Fetching shared files from GitHub..."
    VERSION=$(python3 -c "import json; print(json.load(open('$SCRIPT_DIR/../../package.json'))['version'])" 2>/dev/null \
        || python3 -c "import json; print(json.load(open('$SCRIPT_DIR/app/package.json'))['version'])" 2>/dev/null \
        || echo "master")
    REPO="https://raw.githubusercontent.com/elyxlz/vesta/v${VERSION}"

    curl -fsSL "$REPO/app/src/styles/globals.css" -o "$DASHBOARD_SRC/globals.css"

    mkdir -p "$DASHBOARD_SRC/lib"
    curl -fsSL "$REPO/app/src/lib/utils.ts" -o "$DASHBOARD_SRC/lib/utils.ts"

    mkdir -p "$DASHBOARD_SRC/hooks"
    curl -fsSL "$REPO/app/src/hooks/use-mobile.ts" -o "$DASHBOARD_SRC/hooks/use-mobile.ts"

    mkdir -p "$DASHBOARD_SRC/components/ui"
    FILES=$(curl -fsSL "https://api.github.com/repos/elyxlz/vesta/contents/app/src/components/ui?ref=v${VERSION}" \
        | python3 -c "import sys,json; [print(f['name']) for f in json.load(sys.stdin) if f['name'].endswith('.tsx')]")
    for file in $FILES; do
        curl -fsSL "$REPO/app/src/components/ui/$file" -o "$DASHBOARD_SRC/components/ui/$file"
    done
fi

# Patch globals.css — transparent body for iframe
sed -i 's/@apply bg-background text-foreground;/@apply text-foreground;\n    background: transparent;/' "$DASHBOARD_SRC/globals.css"

echo "Synced $(ls "$DASHBOARD_SRC/components/ui/" | wc -l) UI components"
echo "Done."
