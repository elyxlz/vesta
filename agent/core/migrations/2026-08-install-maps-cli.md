---
interruptible: true
---

The `maps` skill (find real places, Google Maps links, directions, day plans) is a default
skill, so it activates on every boot. Its command needs one install on this box.

### 1. Install the `maps` command

```bash
uv tool install --editable ~/agent/skills/maps/cli
command -v maps
```

The last line must print a path under `~/.local/bin`. The install is transactional and safe to
run more than once. If it fails, STOP, leave this migration unmarked, and report it to the user.

### 2. Verify with one probe

```bash
maps doctor || true
```

`doctor` probes each Maps RPC once and names any failing check. A network failure here is not an
install failure: the command is on PATH either way, so continue.

### 3. Mark this migration applied

Call `mark_migration_applied` with this migration's name.
