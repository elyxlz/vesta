#!/usr/bin/env bash
# Sync shared files from the main Vesta app into the dashboard skill.
# Run this before committing dashboard changes or as part of CI.
#
# `design/tokens.json` is the canonical visual-token source and is generated
# before the web outputs are copied. `apps/web/src/components/ui/` is the
# CANONICAL shadcn registry for this repo: stock primitives plus the app's
# design tokens, with no app behavior inside (app wrappers such as
# components/Dialog compose them). This script mirrors it into the dashboard
# skill's own `app/src/components/ui/`. Those primitives are intentionally the
# FULL set, not only what apps/web itself renders, so the dashboard skill (which
# the agent uses to build arbitrary UIs) always has every component on hand.
# Do NOT delete a primitive from apps/web just because it looks unimported there
# (knip ignores ui/ for that reason) -- the dashboard is the other consumer.
# The ui/ mirror below uses rsync --delete so the two trees stay strictly 1-to-1
# and CI's dashboard-sync-check catches any drift in either direction.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DASHBOARD="$REPO_ROOT/agent/skills/dashboard/app"
DASHBOARD_SRC="$DASHBOARD/src"
APP_SRC="$REPO_ROOT/apps/web/src"

python3 "$REPO_ROOT/scripts/sync-design-tokens.py"

mkdir -p "$DASHBOARD_SRC/lib" "$DASHBOARD_SRC/hooks" "$DASHBOARD_SRC/components/ui"

cp "$REPO_ROOT/apps/web/components.json" "$DASHBOARD/components.json"
cp "$APP_SRC/index.css" "$DASHBOARD_SRC/index.css"
cp "$APP_SRC/design-tokens.css" "$DASHBOARD_SRC/design-tokens.css"
cp "$APP_SRC/lib/utils.ts" "$DASHBOARD_SRC/lib/utils.ts"
cp "$APP_SRC/hooks/use-mobile.ts" "$DASHBOARD_SRC/hooks/use-mobile.ts"
cp "$APP_SRC/hooks/use-media-query.ts" "$DASHBOARD_SRC/hooks/use-media-query.ts" # use-mobile delegates to it
cp "$APP_SRC/hooks/use-scroll-fade.ts" "$DASHBOARD_SRC/hooks/use-scroll-fade.ts" # ui/scroll-shell imports it
# Strict mirror (delete-on-sync) so the dashboard's ui/ exactly matches the
# canonical registry; a primitive removed from one side fails the CI check.
rsync -a --delete --include='*.tsx' --exclude='*' "$APP_SRC/components/ui/" "$DASHBOARD_SRC/components/ui/"

# Patch index.css for iframe embedding (transparent background, tailwind sources)
# Use perl for portable in-place editing (BSD/macOS sed differs from GNU sed).
perl -i -pe 's/bg-background ?//g; s/ bg-background//g' "$DASHBOARD_SRC/index.css"
perl -i -pe 's|^(\s*html \{)$|$1\n    background: transparent;|; s|^(\s*body \{)$|$1\n    background: transparent;|' "$DASHBOARD_SRC/index.css"
perl -i -pe 'print "\@source \"./components/ui\";\n\@source \"./lib\";\n\@source \"./hooks\";\n" if $. == 1' "$DASHBOARD_SRC/index.css"

# Dashboard cards are flat: neutralize the shared Card's shadow in the dashboard copy only
# (apps/web keeps shadow-md). Appended here so the rule lives in the synced index.css without
# touching the canonical apps/web source. See agent/skills/dashboard/design/SKILL.md.
cat >> "$DASHBOARD_SRC/index.css" <<'CARD_FLAT_CSS'

/* Dashboard cards are flat: drop the base Card's shadow while keeping its hairline ring
   for edge definition, by zeroing only the shadow layer of the composed box-shadow (the
   ring uses its own var, so it survives). See the "Cards are flat" design rule. */
[data-slot="card"] {
  --tw-shadow: 0 0 #0000;
}
CARD_FLAT_CSS

# Guard: every font the synced index.css @imports must be a dependency of the dashboard's own
# package.json. The CSS is synced but package.json is NOT, so a font newly added to apps/web (e.g.
# jetbrains-mono) lands in the dashboard's CSS while its package is missing — the agent's dashboard
# build then crashes on the unresolved @import. Catch it here (and in CI's dashboard-sync-check),
# not at agent build time. Fix = add the font to agent/skills/dashboard/app/package.json with the
# version from apps/web/package.json.
missing=()
while IFS= read -r font; do
  [ -z "$font" ] && continue
  grep -q "\"$font\"" "$DASHBOARD/package.json" || missing+=("$font")
done < <(grep -oE '@fontsource-variable/[a-z0-9-]+' "$DASHBOARD_SRC/index.css" | sort -u)
if [ "${#missing[@]}" -gt 0 ]; then
  echo "ERROR: index.css imports fonts the dashboard package.json doesn't depend on: ${missing[*]}" >&2
  echo "  Add each to agent/skills/dashboard/app/package.json (version from apps/web/package.json), then re-run." >&2
  exit 1
fi

echo "Synced $(ls "$DASHBOARD_SRC/components/ui/" | wc -l) UI components"
