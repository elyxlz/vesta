# Upstream Sync - Setup

One-time, at birth: attach your workspace (`~`) to the version Vesta's daemon serves, so
later upgrades can sync it. Silent, no asking.

```bash
bash ~/agent/core/skills/upstream-sync/scripts/attach.sh
```

It prints `attached: ...` and you're done. From now on the `upstream-sync` skill keeps your
workspace current after each upgrade.
