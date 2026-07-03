Your home is a git repo, but still in the old shape: a sparse checkout wired straight to the Vesta monorepo. Convert it once to the current shape, where Vesta's daemon serves your home's stock files as a bundle over the local machine, tagged `agent-v<version>` (see `~/agent/core/skills/workspace-sync/SKILL.md` for how it works). Check which state you are in, do only the matching step, and finish. Re-running is safe: attach.sh is idempotent, and a converted home no longer matches the old shape.

### 1. Check the workspace state

If `~/.git` does not exist, there is nothing to convert: your home attaches to the current workspace on its own the first time a skill is installed or a sync runs. Go to the final step.

Otherwise run the attach script and read its exit code:

```bash
cd ~ && bash agent/core/skills/workspace-sync/scripts/attach.sh; echo "exit: $?"
```

- Exit 0: already attached to the current workspace. Nothing to convert; go to the final step.
- Exit 4: old-shape workspace. Continue with step 2.
- Anything else (exit 3, or a failed fetch): your version's files are not available from Vesta's daemon right now. Not a shape problem and not yours to fix; go to the final step, and the workspace-sync flow will attach later.

### 2. Convert the old workspace

```bash
cd ~
tar czf ~/agent-backup.tar.gz agent       # safety net, keep until verified
ls ~/agent/skills > /tmp/installed-skills # what installed means today
mv ~/.git ~/.git-legacy                   # retire the old repo (delete on a later dream)
bash agent/core/skills/workspace-sync/scripts/attach.sh
```

If this attach fails (failed fetch, or exit 3), stop and go to the final step anyway: the old repo is retired, which is this migration's whole job, and your files on disk are untouched. The workspace-sync flow completes the attach once your version's files are available from Vesta's daemon.

### 3. Drop superseded stock, then reconcile your personalizations (only if the attach succeeded)

First delete old files the current stock no longer ships, so they don't get baked into your customizations commit and rebased forward forever:

```bash
rm -rf ~/agent/skills/upstream-sync   # superseded by the core workspace-sync skill; not yours
rm -rf ~/agent/tests                  # dev-only tree that a box never carries
rm -f ~/agent/pyproject.toml ~/agent/uv.lock   # stale leftovers of the engine move
```

Now `git status` shows every remaining file where your content differs from stock. Judge each one: keep yours, take stock (`git checkout -- <file>`), or integrate both. A file whose only diff is stock that moved or got deleted is not a personalization, take stock. For `agent/MEMORY.md`, keep your accumulated knowledge and adopt the stock structure. Then:

```bash
git add -A && git commit -m "migrated: local customizations"
```
