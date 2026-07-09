Your installed skills only change when you rebase your workspace onto the stock snapshot
of the version you run (see `~/agent/core/skills/workspace-sync/SKILL.md`). Some boxes
skipped or half-finished that sync and are still running old skill copies. One known
case: an old `notifications` skill whose `notif-interrupt-rules.py` writes rules to
`~/agent/data/notification_policy.json`, a legacy file the current agent deletes on
every boot, so those rules silently vanish across restarts.

The workspace-sync skill itself ships with your core, so the copy at
`~/agent/core/skills/workspace-sync/` is already the current one. Use it now for one
full, verified sync so every other skill is brought current too. Safe to re-run: an
already-synced workspace passes step 1 and step 2 becomes a no-op.

### 1. Check where you stand

```bash
cd ~
VERSION="$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
bash agent/core/skills/workspace-sync/scripts/fetch-workspace.sh
git merge-base --is-ancestor "agent-v$VERSION" HEAD && echo synced || echo needs-sync
```

- `needs-sync`: continue with step 2.
- `synced`: your base is current, but stale files can still ride along in your own
  commits, so do step 3 anyway.
- The fetch fails or the tag does not exist: Vesta's daemon has no snapshot for your
  version (an unconverted or unmanaged-core box). Nothing you can do here; mention it
  to the user and finish.

### 2. Sync

Follow the Sync section of `~/agent/core/skills/workspace-sync/SKILL.md` as written
(checkpoint commit, rebase onto `agent-v$VERSION`, set-cone.sh, then
`mark_workspace_synced`), with two adjustments for this pass:

- When a conflict is inside a skill's scripts or code and you never deliberately edited
  that file, take the stock side. Your own content (filled-in personalization stubs,
  notes, files you created) stays on top as usual.
- Skip the `restart_vesta` call for now; step 4 covers the restart.

### 3. Verify the skills actually match stock

```bash
git -C ~ diff --stat "agent-v$VERSION" -- agent/skills agent/core/skills
```

Every line must be a change you made on purpose. Anything else is stale stock riding
along in your commits; make it match stock, per file:

```bash
git -C ~ checkout "agent-v$VERSION" -- <path>   # stock still ships it: take stock
git -C ~ rm -r <path>                           # stock deleted it: drop it
```

Commit what you changed: `git -C ~ add -A && git -C ~ commit -m "drop stale stock"`.

Concrete check for the known case: if you have the `notifications` skill,
`~/agent/skills/notifications/notif-interrupt-rules.py` must be gone and the skill must
contain a `cli/` directory. The current skill manages rules through your config API, so
they survive restarts. If you had interrupt rules through the old script, they were
lost; re-create the ones you still want with the current skill (your past conversations
can remind you which rules you had).

### 4. Load the refreshed skills

If step 2 rebased or step 3 committed anything, call `restart_vesta`, but only after
the final step below has marked this migration applied, so it does not re-run on the
way back up. If nothing changed, no restart is needed.
