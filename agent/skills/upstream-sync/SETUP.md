# Upstream Sync Setup

First-time only. The ongoing checkpoint + merge flow lives in [SKILL.md](SKILL.md).

## 1. Init

`$AGENT_NAME` and `$VESTA_UPSTREAM_REF` are in `/run/vestad-env`.

```bash
cd ~
git init
git remote add origin https://github.com/elyxlz/vesta.git
git sparse-checkout init --no-cone
printf '/agent/\n!/agent/core/\n!/agent/pyproject.toml\n!/agent/uv.lock\n/.gitignore\n' > .git/info/sparse-checkout
git config user.name "$AGENT_NAME"
git config user.email "$AGENT_NAME@vesta"
git checkout -b "$AGENT_NAME"
```

Sparse keeps `agent/core/`, `pyproject.toml`, `uv.lock` out of the worktree (vestad bind-mounts them read-only). Root `.gitignore` arrives on the first merge.

## 2. Local ignores

Write `~/agent/.gitignore` with bulky/machine-local globs: `*.bin *.onnx *.pt *.db *.sqlite *.mp3 *.mp4 *.wav *.zip *.tar.gz node_modules/ dist/ .venv/ __pycache__/`. Add anything else you spot.

## 3. Populate index, skip-worktree bind mounts

```bash
git -C ~ fetch origin "$VESTA_UPSTREAM_REF"
git -C ~ read-tree FETCH_HEAD 2>/dev/null || true
git -C ~ sparse-checkout reapply
if mount | grep -q '/root/agent/core '; then
  git -C ~ ls-files agent/core agent/pyproject.toml agent/uv.lock | xargs -r git -C ~ update-index --skip-worktree
fi
```

## 4. First merge

Follow [SKILL.md](SKILL.md) from step 2 (checkpoint + merge). On this first merge only, add `--allow-unrelated-histories`:

```bash
git -C ~ merge FETCH_HEAD --no-edit --allow-unrelated-histories
```

Expect a wall of `warning: unable to unlink ...: Read-only file system` for `agent/core/` paths. Bind mounts, harmless.
