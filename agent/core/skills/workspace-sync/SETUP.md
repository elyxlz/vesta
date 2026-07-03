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

## Unmanaged core (only if created with `--no-manage-core-code`)

If your core is not a read-only mount, it lives in your workspace instead. Add it to your
cone once, so later workspace syncs include core alongside your skills:

```bash
git sparse-checkout add agent/core        # once, ever
```

From then on the normal workspace sync moves core and skills together. Moving to an OLDER
release transplants your changes instead: `git rebase --onto agent-vOLD agent-vCURRENT`.

That's it. From now on the `workspace-sync` skill keeps your workspace current after each
upgrade.
