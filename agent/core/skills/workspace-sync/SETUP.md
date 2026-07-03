# Workspace Sync - Setup

One-time, at birth: attach your workspace (`~`) to the version Vesta's daemon serves, so
later upgrades can sync it. Silent, no asking.

```bash
bash ~/agent/core/skills/workspace-sync/scripts/attach.sh; echo "exit: $?"
```

- Exit 0: attached. Done.
- Exit 3: your version's snapshot isn't available from Vesta's daemon yet. Not yours to
  fix; skip it. The next workspace sync attaches once it is.
- Exit 4: an old-shape workspace was found (unexpected on a fresh agent). The one-time
  workspace-conversion migration handles that; skip here.

That's it. From now on the `workspace-sync` skill keeps your workspace current after each
upgrade.
