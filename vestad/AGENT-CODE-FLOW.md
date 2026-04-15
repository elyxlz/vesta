# Agent Code Flow

How agent code gets into the container, in both dev and prod modes.

## Image build (Dockerfile)

1. **`git init`** — fresh repo with `origin` remote, sparse checkout set to `agent/` only, `.gitignore` hides runtime dirs (`.claude/`, `data/`, `logs/`)
2. **COPY from build context** — `MEMORY.md`, `prompts/`, `skills/` come from whoever built the image (your local repo in dev, CI release tarball in prod)
3. **Skills pruned** — non-default skills removed to shrink the image
4. **COPY `pyproject.toml` + `uv.lock`** — deps installed into `.venv` in the image layer

At this point the image has:
- `.git/` — fresh repo, no commits yet, `origin` remote configured, sparse checkout for `agent/`
- `.gitignore` — ignores `.claude/`, `data/`, `logs/`
- `agent/MEMORY.md` — from build context
- `agent/prompts/` — from build context
- `agent/skills/` — from build context (pruned)
- `agent/pyproject.toml` + `agent/uv.lock` — from build context
- `agent/.venv/` — installed deps
- No `agent/src/` — that comes from mounts

## Container creation (vestad, `docker.rs` + `agent_code.rs`)

Host paths use vestad’s config dir: `$HOME/.config/vesta/vestad/` (see `main.rs` `config_dir`).

When `manage_core_code` is true, `create_agent` calls `ensure_agent_code` first, then `create_container`:

1. **`ensure_agent_code`** — populates `agent-code/` under the config dir (`.../vestad/agent-code/`):
   - **Dev** (`debug_assertions`): copies `src/vesta/`, `pyproject.toml`, `uv.lock` from the discovered local repo; skips the copy when `agent-code/` is already at least as new as the source tree (mtime check).
   - **Prod**: if `agent-code/` is missing or its `pyproject.toml` version does not match vestad’s `CARGO_PKG_VERSION`, downloads the GitHub release tarball for that version and extracts the same three paths into `agent-code/`.
2. **`create_container`** — writes `agents/{agent}.env` (same config dir) with `WS_PORT`, `AGENT_NAME`, `AGENT_TOKEN`, `IS_SANDBOX=1`, `VESTAD_PORT`, optional `VESTAD_TUNNEL`, optional `VESTA_UPSTREAM_REF`, etc.
3. **Bind mounts** when `manage_core_code` (all `:ro`):
   - `{agent}.env` -> `/run/vestad-env`
   - `agent-code/src/vesta/` -> `/root/agent/src/vesta/`
   - `agent-code/pyproject.toml` -> `/root/agent/pyproject.toml`
   - `agent-code/uv.lock` -> `/root/agent/uv.lock`

So vestad owns `src/vesta/`, `pyproject.toml`, `uv.lock` via mounts. The image owns `MEMORY.md`, `prompts/`, `skills/` — these are the agent's to modify.

## Container startup (entrypoint, `docker.rs`)

The `sh -c` entrypoint runs:

1. **`. /run/vestad-env`** then **`. ~/.bashrc`** (best effort) — env vars (`IS_SANDBOX`, `AGENT_NAME`, `VESTA_UPSTREAM_REF`, ports, etc.)
2. **Git config** — `user.name` is `$AGENT_NAME`; `user.email` is `$AGENT_NAME@vesta`
3. **`uv sync --frozen --project /root/agent`** — ensures deps match the mounted lockfile (mounts may be newer than image)
4. **Git commit** — `git add agent/ .gitignore` then commits if anything is staged. On first boot, everything gets committed. On restarts, only actual changes are committed.
5. **Upstream merge (first boot only)** — when `git describe --tags --abbrev=0` fails (no current tag to describe) and `VESTA_UPSTREAM_REF` is set, fetches that ref from `origin` and runs `git merge -s ours FETCH_HEAD` with `--allow-unrelated-histories` to establish shared ancestry without changing tracked files.
6. **Agent branch** — `git checkout -b "$AGENT_NAME"` if that ref does not exist yet.
7. **`exec uv run --frozen --project /root/agent python -m vesta.main`** — starts the agent

## VESTA_UPSTREAM_REF

Single env var that tells the agent what to sync against:
- **Dev**: set to the git branch vestad was started from (e.g. `feat/agent-source-dir`)
- **Prod**: set to the release tag (e.g. `v0.1.132`)

Updated when vestad starts via `update_all_agent_env_files` (rewrites port, tunnel, and upstream lines in each `agents/*.env`), so the next container start picks up the current upstream.

## What the agent sees at runtime

Git repo root is `$HOME` (`/root` in the image). Tracked tree is under `agent/`.

- `agent/src/vesta/` — vestad's code (mounted, read-only)
- `agent/pyproject.toml` + `uv.lock` — vestad's versions (mounted, read-only)
- `agent/MEMORY.md` — from image build, agent can modify and commit
- `agent/prompts/` — from image build, agent can modify and commit
- `agent/skills/` — from image build, agent can modify and commit
- `.git/` — at `$HOME`, upstream merge base, agent's branch for tracking its changes
- Clean `git status` — runtime dirs hidden by `.gitignore`, sparse checkout hides non-agent files from merges

## Dev vs Prod difference

| | Dev | Prod |
|---|---|---|
| Image | Dockerfile next to cwd or vestad binary → build `vesta:local`; else pull `ghcr.io/elyxlz/vesta:latest` | same |
| `agent-code/` source | copied from local repo | downloaded from release tarball when missing or version mismatch |
| Mounted code | your working tree's `src/vesta/` | release version's `src/vesta/` |
| MEMORY/prompts/skills | from local repo at image build time | from release at image build time |
| `VESTA_UPSTREAM_REF` | git branch (e.g. `feat/foo`) | release tag (e.g. `v0.1.132`) |
