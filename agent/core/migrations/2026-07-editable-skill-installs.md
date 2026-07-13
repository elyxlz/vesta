Several of your skill command line tools were installed as frozen copies (a
plain `uv tool install`), not linked to their source. Upstream sync updates the
skill source under `~/agent`, but a frozen copy keeps running the code it was
built from, so fixes to a skill silently never reach it. The visible symptom is
the app-chat skill delivering every app message to you twice (an old copy and
the agent both write the notification); other skills carry the same latent risk
of running stale code.

This migration reinstalls each of your locally sourced skill tools as an
editable install, so the source directory becomes the install and future
updates take effect on the tool's next run. Running daemons keep their current
code until their next restart, which happens on the next container restart, so
you do not need to restart anything by hand. Safe to run more than once.

### 1. Reinstall each locally sourced skill tool editable

This walks every installed `uv` tool, and for the ones whose source lives under
`~/agent/.../cli` (your own skills, not third party packages) reinstalls it
editable. Already editable tools are reinstalled editable too, which is a no-op
in effect.

```bash
for tool_dir in /root/.local/share/uv/tools/*/; do
  meta=$(find "$tool_dir" -name direct_url.json 2>/dev/null | head -1)
  [ -z "$meta" ] && continue
  src=$(grep -o '"url": *"file://[^"]*"' "$meta" | head -1 | sed -E 's/.*"file:\/\/([^"]*)".*/\1/')
  case "$src" in
    /root/agent/*/cli)
      if [ -d "$src" ]; then
        echo "reinstalling editable: $src"
        uv tool install --editable --force --reinstall "$src"
      fi
      ;;
  esac
done
```

Third party tools (for example `keeper`) do not point at `~/agent` source and
are left untouched. If a reinstall fails because a source directory no longer
exists, that skill is no longer in your checkout: skip it and move on.
