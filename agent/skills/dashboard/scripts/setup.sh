#!/bin/sh
set -eu

# Idempotent dashboard setup: installs deps, builds, starts the daemon, and
# confirms it is actually serving. Safe to re-run; every step is a no-op when
# already done, and a real failure exits loudly instead of leaving a half
# set-up dashboard that looks fine until the next restart. Registering the
# daemon in the restart skill is the agent's step, printed at the end.

DIR="$(cd "$(dirname "$0")" && pwd)"

# Put the dashboard command on PATH; the daemon verbs and the restart line call it by name.
mkdir -p "$HOME/.local/bin"
ln -sf "$DIR/../dashboard" "$HOME/.local/bin/dashboard"

cd "$DIR/../app"

# Dependencies first: the build needs them present before it can resolve an import.
echo "Checking dependencies..."
"$DIR/ensure-deps.sh"

echo "Checking build..."
"$DIR/ensure-build.sh"

echo "Starting daemon..."
"$DIR/../dashboard" daemon start

STATUS=$("$DIR/../dashboard" daemon status)
echo "$STATUS"
case "$STATUS" in
  *'"running":true'*) ;;
  *)
    echo "ERROR: dashboard is not running after start; see ~/agent/logs/dashboard.log" >&2
    exit 1
    ;;
esac

PORT=$(printf '%s' "$STATUS" | sed -n 's/.*"port":\([0-9]*\).*/\1/p')
if ! curl -fsS -o /dev/null "http://localhost:$PORT"; then
  echo "ERROR: dashboard did not answer a 200 on port $PORT; see ~/agent/logs/dashboard.log" >&2
  exit 1
fi

echo "Dashboard setup complete."
echo
echo "Remaining step, yours to do: so the dashboard survives restarts, read the"
echo "restart skill and add this line to your restart daemons:"
echo '  dashboard daemon start'
