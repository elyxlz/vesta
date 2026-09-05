The browser skill runs one daemon that drives two engines, Chromium for ordinary pages and
Camoufox for a site that blocks ordinary automation, behind a single `browser exec --session
<name> [--stealth]` command, and hands a live session to the user through a handover route that
carries a vestad key rather than a bare public URL. This migration brings a box to that shape:
it installs the browser command and both engine environments, stops any browser process left
running outside the daemon, clears the files that process wrote, and points the container's
restart line and this service's exposure at the daemon. Every step reads disk state first, so
running this migration more than once changes nothing further.

### 1. Install the browser system packages

```bash
~/agent/skills/browser/install-engines.sh
```

Installs Chromium and the pinned Camoufox bundle under `/opt/camoufox/<tag>/` when either is
missing, and leaves a binary already present alone.

### 2. Install the browser command and build the two engine environments

```bash
uv tool install --editable --force ~/agent/skills/browser/cli
uv sync --frozen --project ~/agent/skills/browser/engines/chromium
uv sync --frozen --project ~/agent/skills/browser/engines/camoufox
```

### 3. Stop a browser process running outside the daemon

A process whose command line contains `vesta_browser.daemon`, or a Camoufox binary launched from
`~/.cache/camoufox`, predates the daemon and holds files the daemon does not read. Find and stop
each one by scanning `/proc` rather than `pkill`, which the image does not carry. The scan skips
the shell running it, since that shell's own command line carries the same literals as the
patterns it searches for:

```bash
for cmdline in /proc/[0-9]*/cmdline; do
  pid="$(basename "$(dirname "$cmdline")")"
  if [ "$pid" = "$$" ]; then continue; fi
  args="$(tr '\0' ' ' < "$cmdline" 2>/dev/null)" || continue
  case "$args" in
    *vesta_browser.daemon*|*.cache/camoufox*)
      kill "$pid" 2>/dev/null || true
      ;;
  esac
done
sleep 2
for cmdline in /proc/[0-9]*/cmdline; do
  pid="$(basename "$(dirname "$cmdline")")"
  if [ "$pid" = "$$" ]; then continue; fi
  args="$(tr '\0' ' ' < "$cmdline" 2>/dev/null)" || continue
  case "$args" in
    *vesta_browser.daemon*|*.cache/camoufox*)
      kill -9 "$pid" 2>/dev/null || true
      ;;
  esac
done
rm -rf /tmp/vesta-browser-* ~/.cache/camoufox ~/.browser
```

The second pass with `kill -9` catches a process that ignored the first signal. No matching
process, and no matching file, is a no-op. A site signed in through a profile under `~/.browser`
needs signing in again on its next use; say so to the user if a task hits that wall.

### 4. Deregister the browser service

```bash
deregister-service browser
```

A service's public or private exposure sticks until a registration or a deregistration changes
it, and the process this migration stops registered this one public. This step clears that
exposure directly; `deregister-service` succeeds even on a name that is not registered, and the
daemon deregisters this same name for itself on every start, so re-running this step is harmless.

### 5. Point the restart line at the daemon

Read `~/agent/skills/restart/daemons.sh`. If a line starts with `browser`, however indented,
replace that whole line with exactly `browser daemon start`. If no line starts with `browser`,
add that line on its own line, even when the file's last line carries no trailing newline. Create
the file with the header the `restart` skill documents if it does not exist yet. Change no other
line.

```bash
DAEMONS_FILE=~/agent/skills/restart/daemons.sh
if [ ! -f "$DAEMONS_FILE" ]; then
  printf '#!/usr/bin/env bash\n# One <skill> daemon start per line. The restart skill runs each line.\n' > "$DAEMONS_FILE"
fi
if grep -qE '^[[:space:]]*browser($| )' "$DAEMONS_FILE"; then
  sed -i -E 's/^[[:space:]]*browser($| ).*/browser daemon start/' "$DAEMONS_FILE"
else
  if [ -s "$DAEMONS_FILE" ] && [ -n "$(tail -c 1 "$DAEMONS_FILE")" ]; then
    printf '\n' >> "$DAEMONS_FILE"
  fi
  echo 'browser daemon start' >> "$DAEMONS_FILE"
fi
```

### 6. Start the daemon and confirm both engines

```bash
browser daemon start
browser doctor
```

Read `engines.routes.standard.ready` and `engines.routes.stealth.ready` in the `doctor` output.
Both must read `true`. If `doctor` answers an error instead of a report, or either route reads
`false`, STOP, leave this migration unmarked, and report it to the user with what the answer
names.

### 7. Carry Microsoft accounts forward

```bash
ls ~/.microsoft/browser-profiles/ 2>/dev/null
```

Each directory this lists names an account signed in through a profile the browser skill's
Chromium route cannot read. For each one, tell the user in your next message that the account
needs `microsoft auth setup --account <email> --browser` run again, using that directory's name
as `<email>`. Then remove the directory:

```bash
rm -rf ~/.microsoft/browser-profiles
```

Nothing here if the directory does not exist.

### 8. Mark this migration applied

Call `mark_migration_applied` with `name="2026-09-browser-daemon"`.
