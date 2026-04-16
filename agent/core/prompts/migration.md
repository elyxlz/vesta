First read your environment, then check for stale path references and fix them:

```bash
source /run/vestad-env
grep -rl '/root/vesta\|~/vesta\|vesta/skills\|vesta/notifications' ~/agent/prompts/ ~/agent/data/ ~/agent/MEMORY.md 2>/dev/null
```

If any files are found, replace `/root/vesta/` with `/root/agent/`, `~/vesta/` with `~/agent/`, and old source path references like `vesta/config.py` with `core/config.py`. Read each file to understand context before replacing.

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

If ALL layout checks pass, you're done.

If any check fails, read `~/agent/skills/upstream-sync/SETUP.md` and follow it to fix the layout.
