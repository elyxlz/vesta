Some of your skill command line tools may have been installed as frozen copies
(a plain `uv tool install`) instead of linked to their source. Upstream sync
updates the skill source under `~/agent`, but a frozen copy keeps running the
code it was built from, so fixes to a skill silently never reach it. The visible
symptom is the app-chat skill delivering every app message to you twice (an old
frozen copy and the agent both write the notification); any frozen skill carries
the same latent risk of running stale code.

The fix is to reinstall each frozen skill tool as an editable install, so its
source directory becomes the install and future updates apply on its next run.
Every step below is safe to run more than once.

### 1. Check whether this is happening to you

This lists your frozen skill tools. It only reads, it changes nothing:

```bash
tools_dir=$(uv tool dir 2>/dev/null) || tools_dir="$HOME/.local/share/uv/tools"
for tool_dir in "$tools_dir"/*/; do
  meta=$(find "$tool_dir" -name direct_url.json 2>/dev/null | head -1)
  [ -z "$meta" ] && continue
  grep -q '"editable": *true' "$meta" && continue         # editable: fine, skip
  src=$(grep -o '"url": *"file://[^"]*"' "$meta" | head -1 | sed -E 's/.*"file:\/\/([^"]*)".*/\1/')
  case "$src" in "$HOME"/agent/*/cli) [ -d "$src" ] && echo "FROZEN: $src" ;; esac
done
```

Each `FROZEN:` line is one of your own skills running stale code. If it prints
nothing, you have none: skip to the final step. Editable tools and third party
tools (for example `keeper`) never appear here and are left alone.

### 2. Fix each frozen tool

Reinstall each one editable. Reinstalling is transactional: if a rebuild fails
(no network, a half edited skill), `uv` leaves the existing tool exactly as it
was, so this can never break a working tool.

```bash
tools_dir=$(uv tool dir 2>/dev/null) || tools_dir="$HOME/.local/share/uv/tools"
for tool_dir in "$tools_dir"/*/; do
  meta=$(find "$tool_dir" -name direct_url.json 2>/dev/null | head -1)
  [ -z "$meta" ] && continue
  grep -q '"editable": *true' "$meta" && continue
  src=$(grep -o '"url": *"file://[^"]*"' "$meta" | head -1 | sed -E 's/.*"file:\/\/([^"]*)".*/\1/')
  case "$src" in
    "$HOME"/agent/*/cli)
      [ -d "$src" ] || continue
      echo "reinstalling editable: $src"
      uv tool install --editable --force --reinstall "$src" || echo "  reinstall failed, existing install left intact: $src"
      ;;
  esac
done
```

Running daemons keep their current code until their next restart, which happens
on the next container restart, so you do not need to restart anything by hand.

### 3. Confirm

Re-run the check from step 1. It should now print nothing. If a tool still shows
as `FROZEN:` because its reinstall failed for a transient reason (the network
was down), leave this migration unmarked so it retries on the next boot; only
mark it complete once the check comes back empty.
