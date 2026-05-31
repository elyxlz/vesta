# Upstream Sync Setup

First-time only. The ongoing flow lives in [SKILL.md](SKILL.md) (`sync.sh`).

## 1. Init

`$AGENT_NAME` and `$VESTA_UPSTREAM_REF` are in `/run/vestad-env`.

```bash
cd ~
git init
git remote add origin https://github.com/elyxlz/vesta.git
git sparse-checkout init --no-cone
{
  printf '%s\n' '/agent/' '!/agent/core/' '!/agent/pyproject.toml' '!/agent/uv.lock' '!/agent/skills/*/' '/.gitignore'
  for d in agent/skills/*/; do
    [ -d "$d" ] && printf '/%s\n' "$d"
  done
} > .git/info/sparse-checkout
git config user.name "$AGENT_NAME"
git config user.email "$AGENT_NAME@vesta"
git checkout -b "$AGENT_NAME"
```

`agent/skills/*/` is opt-in: only skills already on disk (the defaults baked into the image) are re-included. New upstream skills land in `agent/skills/index.json` (the registry) but stay off disk until `skills-install` adds them.

## 2. Local ignores

Write `~/agent/.gitignore` so the vestad-managed read-only mounts are never tracked, plus bulky machine-local files:

```
/core/
/pyproject.toml
/uv.lock
*.bin
*.onnx
*.pt
*.db
*.sqlite
*.mp3
*.mp4
*.wav
*.zip
*.tar.gz
node_modules/
dist/
.venv/
__pycache__/
```

`agent/core/`, `pyproject.toml` and `uv.lock` are vestad's engine, delivered read-only by the container image. The agent never tracks or contributes them, so git ignores them and `sync.sh` strips them from every merge.

## 3. First sync

```bash
~/agent/skills/upstream-sync/scripts/sync.sh
```

It commits the baked-in defaults as your starting point, then merges upstream (a fresh repo has no shared history, so genuinely different files may conflict, resolve and re-run). From here on, `sync.sh` is the only command you need to pull upstream.
