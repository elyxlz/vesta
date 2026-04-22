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
# Use perl for portable in-place editing (BSD/macOS sed differs from GNU sed).
perl -i -pe 's/bg-background ?//g; s/ bg-background//g' "$DASHBOARD_SRC/index.css"
perl -i -pe 's|^(\s*html \{)$|$1\n    background: transparent;|; s|^(\s*body \{)$|$1\n    background: transparent;|' "$DASHBOARD_SRC/index.css"
perl -i -pe 'print "\@source \"./components/ui\";\n\@source \"./lib\";\n\@source \"./hooks\";\n" if $. == 1' "$DASHBOARD_SRC/index.css"

echo "Synced $(ls "$DASHBOARD_SRC/components/ui/" | wc -l) UI components"
