Check your workspace layout is correct. First read your environment, then run the checks:

```bash
source /run/vestad-env
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

If ALL checks pass, no migration is needed. Move on immediately.

If any check fails, read `~/agent/skills/upstream-sync/SETUP.md` and follow it to fix the layout.
