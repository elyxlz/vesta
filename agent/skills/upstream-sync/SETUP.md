# Upstream Sync Setup

End state: branch `$AGENT_NAME` at `~`, your code under `~/agent`, bulky/local-only files in `~/agent/.gitignore`, one local checkpoint commit, then `origin/$VESTA_UPSTREAM_REF` merged on top.

## 1. Init repo if missing

`$AGENT_NAME` and `$VESTA_UPSTREAM_REF` are already in your env (Read `/run/vestad-env` if you want to confirm).

```bash
if [ ! -d ~/.git ]; then
  cd ~
  git init
  git remote add origin https://github.com/elyxlz/vesta.git
  git sparse-checkout init --no-cone
  printf '/agent/\n!/agent/core/\n!/agent/pyproject.toml\n!/agent/uv.lock\n/.gitignore\n' > .git/info/sparse-checkout
fi
git -C ~ config user.name "$AGENT_NAME"
git -C ~ config user.email "$AGENT_NAME@vesta"
```

The sparse pattern keeps `agent/core/`, `agent/pyproject.toml`, `agent/uv.lock` out of the worktree (vestad bind-mounts them read-only). The root `.gitignore` arrives via the upstream merge in §6.

## 2. Normalize layout

Repo root keeps only `.git`, `.gitignore`, `.claude`, `agent`. Anything agent-owned (data, logs, notifications, caches) belongs under `~/agent`. Move stragglers in by hand. Don't touch the four roots above.

```bash
mkdir -p ~/.claude
ln -sf ../agent/skills ~/.claude/skills
```

## 3. Branch + ignore rules

```bash
git -C ~ checkout -b "$AGENT_NAME" 2>/dev/null || git -C ~ checkout "$AGENT_NAME"
```

In `~/agent/.gitignore`, list bulky/machine-local stuff: `*.bin`, `*.onnx`, `*.pt`, `*.db`, `*.sqlite`, `*.mp3`, `*.mp4`, `*.wav`, `*.zip`, `*.tar.gz`, `node_modules/`, `dist/`, `.venv/`, `__pycache__/`, plus anything else you spot.

## 4. Populate index from upstream

```bash
git -C ~ fetch origin "$VESTA_UPSTREAM_REF"

# read-tree prints sparse-pattern warnings on the initial sync. Drop stderr;
# real errors will surface from the next git command.
git -C ~ read-tree FETCH_HEAD 2>/dev/null || true
git -C ~ sparse-checkout reapply

# Mark bind-mounted paths skip-worktree so the read-only mounts don't look modified.
if mount | grep -q '/root/agent/core '; then
  git -C ~ ls-files agent/core agent/pyproject.toml agent/uv.lock | xargs -r git -C ~ update-index --skip-worktree
fi
```

## 5. Stage + commit local state

```bash
git -C ~ add agent/ --ignore-errors
git -C ~ reset HEAD -- '*.bin' '*.onnx' '*.pt' '*.db' '*.sqlite' '*.mp3' '*.mp4' '*.wav' '*.zip' '*.tar.gz' '**/node_modules' '**/dist' '**/.venv' '**/__pycache__'
# Drop accidental non-agent deletions so upstream's tree wins on merge. Note:
# `git reset HEAD --` always prints "Unstaged changes after reset" even when
# the tree is clean. Informational.
git -C ~ diff --cached --name-only --diff-filter=D | grep -v '^agent/' | xargs -r git -C ~ reset HEAD -- 2>/dev/null || true
git -C ~ status
```

If `git status` still has bulky junk, add to `~/agent/.gitignore` and re-stage. Once clean:

```bash
git -C ~ commit -m "chore: checkpoint local state before $VESTA_UPSTREAM_REF upstream sync"
```

Skip the commit if nothing's staged.

## 6. Merge upstream

`--allow-unrelated-histories` is needed on the first sync (no shared ancestor); no-op afterward.

```bash
git -C ~ fetch origin "$VESTA_UPSTREAM_REF"
git -C ~ merge FETCH_HEAD --no-edit --allow-unrelated-histories
```

Expect a wall of `warning: unable to unlink ...: Read-only file system` for `agent/core/` paths. Bind-mounts, harmless.

If `.gitignore` conflicts at the root, take upstream: `git checkout --theirs .gitignore && git add .gitignore`. Local ignore rules go in `~/agent/.gitignore`.

For real conflicts in `agent/`, preserve both behaviors. Combine logic, extract helpers, decouple, or rename. Only take one side wholesale if the other is obsolete or a strict subset. After:

```bash
git -C ~ add <resolved-files>
git -C ~ commit --no-edit
```

## 7. Verify

```bash
git -C ~ rev-parse --show-toplevel  # should print /root (i.e. ~)
git -C ~ branch --show-current      # should print $AGENT_NAME
git -C ~ status                     # clean
```
