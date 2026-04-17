#!/usr/bin/env bash
# Sync shared files from the main Vesta app into the dashboard skill.
# Run this before committing dashboard changes or as part of CI.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DASHBOARD="$REPO_ROOT/agent/skills/dashboard/app"
DASHBOARD_SRC="$DASHBOARD/src"
APP_SRC="$REPO_ROOT/apps/web/src"

mkdir -p "$DASHBOARD_SRC/lib" "$DASHBOARD_SRC/hooks" "$DASHBOARD_SRC/components/ui"

cp "$REPO_ROOT/apps/web/components.json" "$DASHBOARD/components.json"
cp "$APP_SRC/index.css" "$DASHBOARD_SRC/index.css"
cp "$APP_SRC/lib/utils.ts" "$DASHBOARD_SRC/lib/utils.ts"
cp "$APP_SRC/hooks/use-mobile.ts" "$DASHBOARD_SRC/hooks/use-mobile.ts"
cp "$APP_SRC/components/ui/"*.tsx "$DASHBOARD_SRC/components/ui/"

# Patch index.css for iframe embedding (transparent background, tailwind sources)
sed -i 's/bg-background //g; s/ bg-background//g; s/bg-background//g' "$DASHBOARD_SRC/index.css"
sed -i '/html {/{n;s|$|\n    background: transparent;|}' "$DASHBOARD_SRC/index.css"
sed -i '/body {/{n;s|$|\n    background: transparent;|}' "$DASHBOARD_SRC/index.css"
sed -i '1s|^|@source "./components/ui";\n@source "./lib";\n@source "./hooks";\n|' "$DASHBOARD_SRC/index.css"

echo "Synced $(ls "$DASHBOARD_SRC/components/ui/" | wc -l) UI components"
