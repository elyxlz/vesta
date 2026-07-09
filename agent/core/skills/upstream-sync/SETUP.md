# Upstream Sync - Setup

One-time, at birth: attach your workspace (`~`) to the version Vesta's daemon serves, so
later upgrades can sync it. Silent, no asking.

```bash
bash ~/agent/core/skills/upstream-sync/scripts/attach.sh
```

It prints `attached: ...` and you're done.

## Unmanaged core (only if created with `--no-manage-core-code`)

If your core is not a read-only mount, it lives in your workspace instead. Add it to your
cone once, so later upstream syncs include core alongside your skills:

```bash
git sparse-checkout add agent/core        # once, ever
```

From then on the normal upstream sync moves core and skills together. Moving to an OLDER
release transplants your changes instead: `git rebase --onto agent-vOLD agent-vCURRENT`.

That's it. From now on the `upstream-sync` skill keeps your workspace current after each
upgrade.
