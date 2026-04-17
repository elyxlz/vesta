First read your environment, then check for stale path references and fix them:

```bash
source /run/vestad-env
grep -rl '/root/vesta\|~/vesta\|vesta/skills\|vesta/notifications' ~/agent/prompts/ ~/agent/data/ ~/agent/MEMORY.md 2>/dev/null
```

If any files are found, replace `/root/vesta/` with `/root/agent/`, `~/vesta/` with `~/agent/`, and old source path references like `vesta/config.py` with `core/config.py`. Read each file to understand context before replacing.

Remove agent prompts that now live in core (the core versions are always up to date via bind mount):

```bash
for f in first_start_greeting.md first_start_setup.md nightly_dream.md notification_suffix.md proactive_check.md dream.md; do
  rm -f ~/agent/prompts/$f
done
```

Then verify your workspace layout:

```bash
test "$(git -C ~ rev-parse --show-toplevel)" = "/root" && echo "OK: repo root"
test "$(git -C ~ branch --show-current)" = "$AGENT_NAME" && echo "OK: branch"
test -d ~/agent/data && echo "OK: agent/data"
test -d ~/agent/prompts && echo "OK: agent/prompts"
test -d ~/agent/skills && echo "OK: agent/skills"
test -L ~/.claude/skills && echo "OK: skills symlink"
test ! -d ~/vesta && echo "OK: ~/vesta removed"
test ! -d ~/data && test ! -d ~/logs && test ! -d ~/notifications && echo "OK: no stale root paths"
test -f ~/agent/.gitignore && echo "OK: gitignore"
git -C ~ diff --quiet && echo "OK: clean tree"
```

If ALL layout checks pass, rebuild skill dependencies and restart services:

```bash
cd ~/agent && uv sync --frozen 2>/dev/null || uv sync
```

For each skill that has a SETUP.md, check if its dependencies need rebuilding (e.g. go binaries, npm packages). Read the SETUP.md and run the install/build steps if the binaries are missing or stale. Then restart any services listed in `~/agent/prompts/restart.md`.

If you made any changes (fixed paths, removed files, rebuilt deps, or fixed layout), restart yourself using `restart_vesta` so the process picks up all changes cleanly. If everything was already correct and no changes were needed, skip the restart.

If any layout check fails, read `~/agent/skills/upstream-sync/SETUP.md` and follow it to fix the layout, then rebuild deps and restart as above.
