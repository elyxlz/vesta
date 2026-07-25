---
name: upstream-sync
description: Sync your workspace after a Vesta upgrade by merging the new stock snapshot into your own history. Use during the upgrade boot turn, or when the user asks you to get up to date or get the latest changes.
---

# Upstream Sync

Your workspace (`~`) is a git repository: a plain full checkout of Vesta's stock content
(your skills and `MEMORY.md`). Vesta's daemon keeps that stock in a per-host snapshot repo,
bind-mounted read-only at `/run/vesta-upstream`: one commit per release, tagged `agent-vX.Y.Z`,
fetched locally (no internet involved). When Vesta upgrades, the core you run changes with it
(it is a read-only mount), and syncing brings the rest of your workspace up to the same
version: merge the tag matching the version you now run, so you take every stock change
without rewriting any of your commits. To contribute changes back to the Vesta project, see
`~/agent/skills/upstream-pr/SKILL.md`.

## Sync (after an upgrade, when the boot turn asks)

Work in `~` and use Git directly. There is no sync wrapper hiding the operation.

First run `git status`. If Git reports an operation already in progress, finish or abandon
that operation before starting another one:

- **Merge in progress:** resolve every conflicted file, `git add <file>`, then
  `git commit --no-edit`; or restore the pre-update state with `git merge --abort`.
- **Rebase in progress:** this is one update interrupted before Vesta switched to merges.
  Resolve every conflicted file, `git add <file>`, then `git rebase --continue`; or restore
  the pre-update state with `git rebase --abort`. Once it is gone, all later updates merge.

If birth was interrupted before it finished creating the initial Git history, bootstrap it
first. Checking `HEAD` also repairs an empty `.git` directory left by an interrupted attach:

```bash
git -C ~ rev-parse -q --verify HEAD >/dev/null 2>&1 || \
  bash ~/agent/core/skills/upstream-sync/scripts/attach.sh
```

Then fetch the stock snapshots from Vesta's read-only local repository. A normal current
container has the mount and uses plain `git fetch`; the fallback exists only for a fleet box
whose container rebuild was deferred before this mount shipped:

```bash
cd ~
if test -d /run/vesta-upstream/upstream.git; then
  git fetch --no-tags /run/vesta-upstream/upstream.git \
    '+refs/tags/agent-v*:refs/tags/agent-v*'
else
  bash ~/agent/core/skills/upstream-sync/scripts/fetch-upstream.sh
fi
VERSION="$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
TAG="agent-v$VERSION"
git rev-parse -q --verify "refs/tags/$TAG"
```

If the tag is already in your history, you are done:

```bash
git merge-base --is-ancestor "$TAG" HEAD
```

Otherwise checkpoint anything not committed, then merge the update. `git add -A` is safe:
the read-only `agent/core/` mount is ignored by the repository.

```bash
git add -A
git diff --cached --quiet || git commit -m checkpoint
git merge --no-ff --no-edit "$TAG"
```

If the merge stops on a conflict, the resolution is yours:

- Conflicts: ALWAYS resolve by hand, and the default is to keep BOTH sides, your change
  AND the stock change, not pick a winner. Do NOT reflexively `git checkout --ours/--theirs`
  or blanket-take one side: that silently drops real work. Even a file you upstreamed comes
  back genericized, so take stock's form and re-apply your local specifics on top rather
  than discarding either. Edit each conflicted file so both sides survive, `git add <file>`,
  then `git commit --no-edit`. `git merge --abort` restores
  exactly the pre-sync state.
- For `agent/MEMORY.md`, keep your accumulated knowledge and adopt the stock structure.
- If the merge brought changes, call `restart_vesta` so the new skills load. Completion is
  read directly from Git history; there is no separate state marker to maintain.

## Status

After fetching and setting `TAG` as above, standard Git shows the complete answer:

```bash
git status --short
git merge-base --is-ancestor "$TAG" HEAD && echo synced || echo needs-sync
git log --oneline "$TAG..HEAD"
```
