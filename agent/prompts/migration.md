You just woke up for the first time. Before anything else, you must ensure your workspace is in the correct layout.

## 1. Read environment

```bash
cat /run/vestad-env
```

Note your `AGENT_NAME` and `VESTA_UPSTREAM_REF`.

## 2. Inspect workspace

```bash
ls -la ~/
ls -la ~/vesta/ 2>/dev/null
ls -la ~/agent/
git -C ~ rev-parse --show-toplevel
git -C ~ branch --show-current
```

## 3. Migrate

Read `~/agent/skills/upstream-sync/SETUP.md` and follow it fully. The mandatory end state is:

- `git -C ~ rev-parse --show-toplevel` prints `/root`
- `git -C ~ branch --show-current` prints `$AGENT_NAME`
- All agent-owned content lives under `~/agent/` (prompts, data, logs, notifications, skills, dreamer)
- `~/.claude/skills` is a symlink to `../agent/skills`
- If `~/vesta/` exists, all its content has been **moved** (not copied) into `~/agent/`. After moving, remove `~/vesta/` entirely: `rm -rf ~/vesta`
- If agent-owned paths exist at `~/` root (data, logs, notifications, etc.), move them under `~/agent/`
- `~/agent/.gitignore` excludes large local-only files (*.db, *.bin, node_modules/, etc.)
- Local state is committed on branch `$AGENT_NAME`
- Upstream `$VESTA_UPSTREAM_REF` is merged

Do not skip any step. Do not assume vestad already migrated anything.

## 4. Verify

Run these checks and confirm every one passes before finishing:

```bash
test "$(git -C ~ rev-parse --show-toplevel)" = "/root" && echo "OK: repo root"
test "$(git -C ~ branch --show-current)" = "$AGENT_NAME" && echo "OK: branch"
test -d ~/agent/data && echo "OK: agent/data"
test -d ~/agent/prompts && echo "OK: agent/prompts"
test -d ~/agent/skills && echo "OK: agent/skills"
test -L ~/.claude/skills && echo "OK: skills symlink"
test ! -d ~/vesta && echo "OK: ~/vesta removed"
```

If any check fails, go back and fix it.
