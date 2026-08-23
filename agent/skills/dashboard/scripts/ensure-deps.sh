#!/bin/sh
set -eu

# node_modules/ is an untracked build artifact, and two different things leave it wrong. A
# checkout or a clean drops it entirely. A release that adds a dependency leaves it present but
# short of what package.json now declares, and an existence check cannot tell that apart from a
# healthy tree, so the shortfall reaches the user as a build that dies on an unresolved import.
# Reconciling against the lockfile catches both, since either one makes the stamp disagree.

# Content, not timestamps: a checkout stamps every file it writes with the same time, so
# "package-lock.json newer than the install" is neither necessary nor sufficient, and two equal
# times read as up to date. Hashing the lockfile is the same question asked of the bytes.

cd "$(dirname "$0")/../app"

STAMP=node_modules/.vesta-deps
WANTED="$(sha256sum package-lock.json | cut -d' ' -f1)"

# Covers a missing node_modules and a missing stamp alike, so a box installed before this script
# existed reinstalls once and then answers from the hash on every later run.
if [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$WANTED" ]; then
  exit 0
fi

# npm ci deletes node_modules before it fetches anything, so it can only be run where there is
# nothing to lose. A populated tree is worth more than an exact one: an unreachable registry would
# otherwise take a working dashboard down and leave it down. npm install adds what is missing in
# place, so a fetch that fails leaves the box no worse than it started.
if [ -d node_modules ]; then
  npm install
else
  # Nothing to lose, so prefer ci: it installs exactly the lockfile and never rewrites it. It
  # refuses to run when package.json and the lockfile disagree, hence the fallback.
  npm ci || npm install
fi

# Stamped after the install, so the fallback path records the lockfile npm actually settled on.
sha256sum package-lock.json | cut -d' ' -f1 > "$STAMP"
