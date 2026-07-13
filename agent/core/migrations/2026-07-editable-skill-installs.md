Several of your skill command line tools were installed as frozen copies (a
plain `uv tool install`), not linked to their source. Upstream sync updates the
skill source under `~/agent`, but a frozen copy keeps running the code it was
built from, so fixes to a skill silently never reach it. The visible symptom is
the app-chat skill delivering every app message to you twice (an old copy and
the agent both write the notification); other skills carry the same latent risk
of running stale code.

This migration reinstalls each frozen, locally sourced skill tool as an editable
install, so the source directory becomes the install and future updates take
effect on the tool's next run. It touches only frozen tools whose source is one
of your own skills; already editable tools and third party tools are left alone.
Reinstalling is transactional: if a rebuild fails (no network, a half edited
skill), the existing working tool is left exactly as it was, never removed. So
every step is safe to run more than once.

### 1. Reinstall each frozen skill tool editable

```bash
tools_dir=$(uv tool dir 2>/dev/null) || tools_dir="$HOME/.local/share/uv/tools"
for tool_dir in "$tools_dir"/*/; do
  meta=$(find "$tool_dir" -name direct_url.json 2>/dev/null | head -1)
  [ -z "$meta" ] && continue
  grep -q '"editable": *true' "$meta" && continue          # already editable: nothing to fix
  src=$(grep -o '"url": *"file://[^"]*"' "$meta" | head -1 | sed -E 's/.*"file:\/\/([^"]*)".*/\1/')
  case "$src" in
    "$HOME"/agent/*/cli) : ;;                               # one of your own skills
    *) continue ;;                                          # third party or unknown: leave alone
  esac
  [ -d "$src" ] || { echo "skip (source gone): $src"; continue; }
  echo "reinstalling editable: $src"
  uv tool install --editable --force --reinstall "$src" || echo "  reinstall failed, existing install left intact: $src"
done
```

Running daemons keep their current code until their next restart, which happens
on the next container restart, so you do not need to restart anything by hand.

If some tools failed to reinstall for a transient reason (the network was down
at boot), leave this migration unmarked so it retries on the next boot; the
tools that already converted are skipped on the retry. Only mark it complete
once every applicable tool is either editable or has a source directory that no
longer exists.
