Your git workspace converts from a sparse monorepo checkout to the published agent branch (see `~/agent/core/skills/workspace-sync/SKILL.md` for how the branch works). Check which state you are in, do only that branch, and finish. Re-running any of this is safe: attach.sh is idempotent and a converted workspace no longer matches the legacy shape.

### 1. Check the workspace state

If `~/.git` does not exist, there is nothing to convert: your workspace attaches automatically the first time a skill is installed or a sync runs. Go to the final step.

Otherwise run the attach script and branch on its exit code:

```bash
cd ~ && bash agent/core/skills/workspace-sync/scripts/attach.sh; echo "exit: $?"
```

- Exit 0: already on the agent branch. Nothing to convert; go to the final step.
- Exit 4: legacy workspace. Continue with step 2.
- Anything else (exit 3, or a failed fetch): your version's files are not reachable on the remote right now. Not a workspace-shape problem and not yours to fix; go to the final step and the workspace-sync flow will attach later.

### 2. Convert the legacy workspace

```bash
cd ~
tar czf ~/agent-backup.tar.gz agent       # safety net, keep until verified
ls ~/agent/skills > /tmp/installed-skills # what installed means today
mv ~/.git ~/.git-legacy                   # retire the old repo (delete on a later dream)
bash agent/core/skills/workspace-sync/scripts/attach.sh
```

If this attach fails (failed fetch, or exit 3), stop and go to the final step anyway: the legacy repo is retired, which is this migration's whole job, and your files on disk are untouched. The workspace-sync flow completes the attach once the remote content is reachable.

### 3. Reconcile your personalizations (only if the attach succeeded)

`git status` now shows every file where your content differs from stock. Judge each one: keep yours, take stock (`git checkout -- <file>`), or integrate both. For `agent/MEMORY.md`, keep your accumulated knowledge and adopt upstream's structure. Then:

```bash
rm -f ~/agent/pyproject.toml ~/agent/uv.lock   # stale leftovers of the engine move
git add -A && git commit -m "migrated: local customizations"
```
