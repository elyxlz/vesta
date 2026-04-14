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

## Container creation (vestad, `docker.rs`)

vestad calls `create_container` which:

1. **Writes `{agent}.env`** to host disk — contains `WS_PORT`, `AGENT_NAME`, `AGENT_TOKEN`, `IS_SANDBOX=1`, `VESTAD_PORT`, `VESTA_UPSTREAM_REF`, etc.
2. **Resolves `agent-code/` dir** on host (`~/.config/vesta/agent-code/`):
   - **Dev** (`debug_assertions`): copies `src/vesta/`, `pyproject.toml`, `uv.lock` from local repo into `agent-code/`
   - **Prod**: downloads release tarball matching vestad's version, extracts the same three items into `agent-code/`
3. **Bind mounts** (all `:ro`):
   - `{agent}.env` -> `/run/vestad-env`
   - `agent-code/src/vesta/` -> `/root/vesta/agent/src/vesta/`
   - `agent-code/pyproject.toml` -> `/root/vesta/agent/pyproject.toml`
   - `agent-code/uv.lock` -> `/root/vesta/agent/uv.lock`

So vestad owns `src/vesta/`, `pyproject.toml`, `uv.lock` via mounts. The image owns `MEMORY.md`, `prompts/`, `skills/` — these are the agent's to modify.

## Container startup (entrypoint, `docker.rs`)

The `sh -c` entrypoint runs:

1. **`. /run/vestad-env`** — sources env vars (`IS_SANDBOX`, `AGENT_NAME`, `VESTA_UPSTREAM_REF`, ports, etc.)
2. **Git config** — sets `user.name` and `user.email` to `$AGENT_NAME`
3. **`uv sync --frozen`** — ensures deps match the mounted lockfile (mounts may be newer than image)
4. **Git commit** — `git add agent/ .gitignore` then commits if anything is staged. On first boot, everything gets committed. On restarts, only actual changes are committed.
5. **Upstream merge (first boot only)** — if no tags exist locally, fetches `$VESTA_UPSTREAM_REF` from origin and does `git merge -s ours` to establish shared ancestry without modifying any files on disk. This gives future upstream syncs a merge base.
6. **Agent branch** — creates branch named `$AGENT_NAME` if it doesn't exist. Agent commits its changes here.
7. **`exec uv run python -m vesta.main`** — starts the agent

## VESTA_UPSTREAM_REF

Single env var that tells the agent what to sync against:
- **Dev**: set to the git branch vestad was started from (e.g. `feat/agent-source-dir`)
- **Prod**: set to the release tag (e.g. `v0.1.132`)

Updated by vestad on restart via `update_all_agent_env_files`, so agents always sync against the current upstream.

## What the agent sees at runtime

- `agent/src/vesta/` — vestad's code (mounted, read-only)
- `agent/pyproject.toml` + `uv.lock` — vestad's versions (mounted, read-only)
- `agent/MEMORY.md` — from image build, agent can modify and commit
- `agent/prompts/` — from image build, agent can modify and commit
- `agent/skills/` — from image build, agent can modify and commit
- `.git/` — fresh repo with upstream merge base, agent's branch for tracking its changes
- Clean `git status` — runtime dirs hidden by `.gitignore`, sparse checkout hides non-agent files from merges

## Dev vs Prod difference

| | Dev | Prod |
|---|---|---|
| Image | `vesta:local` (built locally) | `ghcr.io/elyxlz/vesta:v0.1.x` (CI) |
| `agent-code/` source | copied from local repo | downloaded from release tarball |
| Mounted code | your working tree's `src/vesta/` | release version's `src/vesta/` |
| MEMORY/prompts/skills | from local repo at image build time | from release at image build time |
| `VESTA_UPSTREAM_REF` | git branch (e.g. `feat/foo`) | release tag (e.g. `v0.1.132`) |
