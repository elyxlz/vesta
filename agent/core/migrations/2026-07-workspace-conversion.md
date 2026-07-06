Your workspace (`~`) is a git repo, but still in the old shape: a sparse checkout wired straight to the Vesta monorepo. Convert it once to the current shape, where Vesta's daemon serves your workspace's stock files as a bundle over the local machine, tagged `agent-v<version>` (see `~/agent/core/skills/workspace-sync/SKILL.md` for how it works). Run step 1; its exit code tells you which step to do next. Re-running is safe: attach.sh is idempotent, and a converted workspace no longer matches the old shape.

### 1. Attach, and read the exit code

```bash
cd ~ && bash agent/core/skills/workspace-sync/scripts/attach.sh; echo "exit: $?"
```

- Exit 4: old-shape workspace (attach refused to touch it). Convert it in step 2.
- Exit 0: attached (your workspace was already converted, or had no repo yet and just got one). If `git status` shows changes, reconcile them in step 3; otherwise you're done.
- Anything else (exit 3, or a failed fetch): your version's files aren't available from Vesta's daemon right now. Not yours to fix; you're done, and the next workspace sync attaches once they are.

### 2. Convert the old workspace

Retire the old repo and attach the new one, but put the old one back if the attach fails, so you are never left without a working repo:

```bash
cd ~
tar czf ~/agent-backup.tar.gz agent       # safety net, keep until verified
mv ~/.git ~/.git-legacy                   # retire the old repo (delete on a later dream)
if ! bash agent/core/skills/workspace-sync/scripts/attach.sh; then
  rm -rf ~/.git                           # drop the half-made repo the failed attach left
  mv ~/.git-legacy ~/.git                 # restore the working repo, untouched
  echo "conversion deferred: this version's snapshot isn't available from Vesta's daemon"
fi
```

If you saw the `conversion deferred` message, stop: your old workspace is back exactly as it was and still works. This is an unmanaged-core box whose core predates the workspace feature, so its snapshot will not appear on its own. Tell the user; they convert it by hand once its core is brought current. Otherwise continue to step 3.

### 3. Drop superseded stock, then reconcile your changes

First delete old files the current stock no longer ships, so they don't get baked into your commit and rebased forward forever:

```bash
rm -rf ~/agent/skills/upstream-sync   # superseded by the core workspace-sync skill; not yours
rm -rf ~/agent/tests                  # dev-only tree a workspace never carries
rm -f ~/agent/pyproject.toml ~/agent/uv.lock   # stale leftovers of the engine move
```

Now `git status` shows every file where your content differs from stock. Judge each: keep yours, take stock (`git checkout -- <file>`), or integrate both. A file whose only diff is stock that moved or got deleted is not yours, take stock. For `agent/MEMORY.md`, keep your accumulated knowledge and adopt the stock structure. Then:

```bash
git add -A --sparse && git commit -m "my customizations"
```

(`--sparse` lets git stage files in directories of your own under `agent/`, which start outside the sparse cone.) Then widen the cone to cover them, so no later sparse-checkout reapply prunes them:

```bash
bash agent/core/skills/workspace-sync/scripts/set-cone.sh
```
