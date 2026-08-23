#!/bin/sh
set -eu

# dist/ is an untracked build artifact carrying the same defect node_modules had: asking whether
# it exists cannot tell a current bundle from one built before a release changed the source, so a
# box that already has one keeps serving the old bundle and nothing ever signals it. Reconcile
# against the build's inputs instead, stamped into dist/ at build time.

# Inputs, never the output. Hashing dist/ would answer "did the output change", which is circular.
# package-lock.json is an input because a dependency change alters the bundle too.

# LC_ALL=C sort is what makes this deterministic: find returns directory order, and ext4 seeds its
# directory hash per filesystem, so the same content would otherwise digest differently per box
# and rebuild on every launch. -r keeps an empty list from leaving xargs reading stdin.

cd "$(dirname "$0")/../app"

STAMP=dist/.vesta-build
WANTED="$(find src index.html vite.config.ts package-lock.json tsconfig.json tsconfig.app.json tsconfig.node.json \
  -type f -print0 2>/dev/null | LC_ALL=C sort -z | xargs -0 -r sha256sum | sha256sum | cut -d' ' -f1)"

# Covers a missing dist/ and a missing stamp alike, so a box built before this script existed
# rebuilds once and then answers from the digest on every later run.
if [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$WANTED" ]; then
  exit 0
fi

# The build empties dist/, so the stamp is written after it and cannot outlive the bundle it
# describes, the same way the deps stamp cannot outlive its node_modules.
npx vite build
printf '%s\n' "$WANTED" > "$STAMP"
