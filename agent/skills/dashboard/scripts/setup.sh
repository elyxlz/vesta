#!/bin/sh
set -eu

# Idempotent one-shot dashboard setup: installs deps, builds, starts the
# daemon, confirms it is actually serving, and appends the guarded
# restart-skill daemon line once. Safe to re-run; every step is a no-op when
# already done, and a real failure exits loudly instead of leaving a half
# set-up dashboard that looks fine until the next restart.

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
"$DIR/daemon" start

STATUS=$("$DIR/daemon" status)
echo "$STATUS"
case "$STATUS" in
  *'"http_ok":true'*) ;;
  *)
    echo "ERROR: dashboard did not answer a 200 after start; see 'screen -r dashboard'" >&2
    exit 1
    ;;
esac

RESTART_SKILL=~/agent/skills/restart/SKILL.md
LINE='running dashboard || { ~/agent/skills/dashboard/scripts/daemon start; sleep 1; }'
if [ -f "$RESTART_SKILL" ] && ! grep -qF "$LINE" "$RESTART_SKILL"; then
  printf '\n```bash\n%s\n```\n' "$LINE" >> "$RESTART_SKILL"
  echo "Appended dashboard daemon line to restart skill."
fi

echo "Dashboard setup complete."
