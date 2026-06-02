# Upstream Sync Setup

First-time only. The ongoing flow lives in [SKILL.md](SKILL.md) (`sync.sh`).

## 1. Init

`$AGENT_NAME` and `$VESTA_UPSTREAM_REF` are in `/run/vestad-env`. Run the init script (idempotent):

```bash
~/agent/skills/upstream-sync/scripts/init.sh
```

It inits the repo, sets the remote, pins the sparse-checkout cone, configures your identity, and creates your branch. Do not hand-write the cone: `init.sh` builds the patterns with `find` so they stay repo-relative regardless of cwd. `agent/skills/*/` is opt-in: only skills already on disk (the defaults baked into the image) are re-included. New upstream skills land in `agent/skills/index.json` (the registry) but stay off disk until `skills-install` adds them.

## 2. Local ignores (bulky files only)

`sync.sh` already ignores the vestad-managed mounts (`agent/core/`, `pyproject.toml`, `uv.lock`) by writing them to `.git/info/exclude`, so you don't list those. Just add bulky machine-local globs:

```
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

## 3. First sync

```bash
~/agent/skills/upstream-sync/scripts/sync.sh
```

It commits the baked-in defaults as your starting point, then merges upstream (a fresh repo has no shared history, so genuinely different files may conflict, resolve and re-run). From here on, `sync.sh` is the only command you need to pull upstream.
