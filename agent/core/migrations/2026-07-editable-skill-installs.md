Some of your skill command line tools may be installed as frozen copies (a plain
`uv tool install`) instead of linked to their source. Upstream sync updates the
skill source, but a frozen copy keeps running the code it was built from, so
fixes to a skill silently never reach it. The visible symptom is the app-chat
skill delivering every app message to you twice; any frozen skill carries the
same latent risk of running stale code.

The fix is to reinstall each frozen skill tool as an editable install, so its
source directory becomes the install and future updates apply on its next run.
Every step below is safe to run more than once.

### 1. Check whether this is happening to you

This reads only, it changes nothing. It lists your frozen skill tools and their
source:

```bash
tools_dir=$(uv tool dir 2>/dev/null) || tools_dir="$HOME/.local/share/uv/tools"
for tool_dir in "$tools_dir"/*/; do
  meta=$(find "$tool_dir" -name direct_url.json 2>/dev/null | head -1)
  [ -z "$meta" ] && continue
  grep -q '"editable": *true' "$meta" && continue          # editable: fine, skip
  src=$(grep -o '"url": *"file://[^"]*"' "$meta" | head -1 | sed -E 's/.*"file:\/\/([^"]*)".*/\1/')
  [ -z "$src" ] && continue                                 # no file:// source: third-party, skip
  [ -d "$src" ] && echo "FROZEN: $(basename "$tool_dir")  <- $src" || echo "FROZEN (source gone): $(basename "$tool_dir")  <- $src"
done
```

Only your own skills (a local `file://` source) appear here, at whatever path
they live; third party tools like `keeper` never do. If nothing prints, you have
none: skip to the final step.

### 2. Fix each frozen tool

This reinstalls each one editable, from its own source:

```bash
tools_dir=$(uv tool dir 2>/dev/null) || tools_dir="$HOME/.local/share/uv/tools"
for tool_dir in "$tools_dir"/*/; do
  meta=$(find "$tool_dir" -name direct_url.json 2>/dev/null | head -1)
  [ -z "$meta" ] && continue
  grep -q '"editable": *true' "$meta" && continue
  src=$(grep -o '"url": *"file://[^"]*"' "$meta" | head -1 | sed -E 's/.*"file:\/\/([^"]*)".*/\1/')
  [ -d "$src" ] || continue
  echo "reinstalling editable: $src"
  uv tool install --editable --force --reinstall "$src" || echo "  reinstall failed, existing install left intact: $src"
done
```

Reinstalling is transactional: if a rebuild fails (no network, a half edited
skill), `uv` leaves the existing tool exactly as it was, so this cannot break a
working tool. Running daemons keep their current code until their next container
restart, so you do not need to restart anything by hand.

### 3. Confirm

Re-run the check from step 1. It should now print nothing. If a tool still shows
as `source gone`, it was installed from an old path that no longer exists: find
that skill's current CLI directory under `~/agent` and reinstall editable from
it (`uv tool install --editable --force --reinstall <dir>`), or if the skill is
no longer installed, drop the stale tool with `uv tool uninstall <tool-name>`.
If a reinstall failed only because the network was down, leave this migration
unmarked so it retries next boot; mark it complete once the check comes back
empty.
