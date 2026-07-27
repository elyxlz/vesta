#!/bin/sh
set -eu

# Idempotent dashboard setup: installs deps, builds, starts the daemon, and
# confirms it is actually serving. Safe to re-run; every step is a no-op when
# already done, and a real failure exits loudly instead of leaving a half
# set-up dashboard that looks fine until the next restart. Registering the
# daemon in the restart skill is the agent's step, printed at the end.

DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$DIR/../app"

if [ ! -d node_modules ]; then
  echo "Installing dependencies..."
  npm install
fi

if [ ! -d dist ]; then
  echo "Building dashboard..."
  npx vite build
fi

echo "Starting daemon..."
"$DIR/../dashboard" daemon start

STATUS=$("$DIR/../dashboard" daemon status)
echo "$STATUS"
case "$STATUS" in
  *'"http_ok":true'*) ;;
  *)
    echo "ERROR: dashboard did not answer a 200 after start; see 'screen -r dashboard'" >&2
    exit 1
    ;;
esac

echo "Dashboard setup complete."
echo
echo "Remaining step, yours to do: add this line inside the fenced Daemons block"
echo "of ~/agent/skills/restart/SKILL.md, matching the guard form already there."
echo '  running dashboard || { dashboard daemon start; sleep 1; }'
