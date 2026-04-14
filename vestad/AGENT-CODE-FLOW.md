# Agent Code Flow

How agent code gets into the container, in both dev and prod modes.

## Image build (Dockerfile)

1. **`git init`** — fresh repo with `origin` remote pointing to GitHub, no history
2. **COPY from build context** — `MEMORY.md`, `prompts/`, `skills/` come from whoever built the image (your local repo in dev, CI release tarball in prod)
3. **Skills pruned** — non-default skills removed to shrink the image
4. **COPY `pyproject.toml` + `uv.lock`** — deps installed into `.venv` in the image layer

At this point the image has:
- `.git/` — fresh repo, no commits yet, `origin` remote configured
- `agent/MEMORY.md` — from build context
- `agent/prompts/` — from build context
- `agent/skills/` — from build context (pruned)
- `agent/pyproject.toml` + `agent/uv.lock` — from build context
- `agent/.venv/` — installed deps
- No `agent/src/` — that comes from mounts

## Container creation (vestad, `docker.rs`)

vestad calls `create_container` which:

1. **Writes `{agent}.env`** to host disk — contains `WS_PORT`, `AGENT_NAME`, `AGENT_TOKEN`, `IS_SANDBOX=1`, `VESTAD_PORT`, etc.
2. **Resolves `agent-code/` dir** on host (`~/.config/vesta/agent-code/`):
   - **Dev** (`debug_assertions`): copies `src/vesta/`, `pyproject.toml`, `uv.lock` from local repo into `agent-code/`
   - **Prod**: downloads release tarball matching vestad's version, extracts the same three items into `agent-code/`
3. **Bind mounts** (all `:ro`):
   - `{agent}.env` -> `/run/vestad-env`
   - `agent-code/src/vesta/` -> `/root/vesta/agent/src/vesta/`
   - `agent-code/pyproject.toml` -> `/root/vesta/agent/pyproject.toml`
   - `agent-code/uv.lock` -> `/root/vesta/agent/uv.lock`

So vestad owns `src/vesta/`, `pyproject.toml`, `uv.lock` via mounts. The image owns `MEMORY.md`, `prompts/`, `skills/` — these are the agent's to modify.

## Container startup (entrypoint, `docker.rs:83-91`)

The `sh -c` entrypoint runs:

1. **`. /run/vestad-env`** — sources env vars (`IS_SANDBOX`, `AGENT_NAME`, `VESTA_VERSION`, ports, etc.)
2. **`uv sync --frozen`** — ensures deps match the mounted lockfile (mounts may be newer than image)
3. **Git commit** — `git diff --quiet agent/` checks if mounted files differ from what git expects. If they do (they will on first boot, since mounts overlay the image), it does `git add agent/ && git commit -m 'initial'`. This resets git to match the actual working tree so `git diff` starts clean.
4. **Upstream merge (first boot only)** — if no tags exist locally, fetches `v$VESTA_VERSION` tag from origin and merges it with `--allow-unrelated-histories`. This establishes shared ancestry so future upstream syncs can do normal merges.
5. **Agent branch** — creates branch named `$AGENT_NAME` if it doesn't exist (e.g. `joemama`). Agent commits its changes here.
6. **`exec uv run python -m vesta.main`** — starts the agent

## What the agent sees at runtime

- `agent/src/vesta/` — vestad's code (mounted, read-only)
- `agent/pyproject.toml` + `uv.lock` — vestad's versions (mounted, read-only)
- `agent/MEMORY.md` — from image build, agent can modify and commit
- `agent/prompts/` — from image build, agent can modify and commit
- `agent/skills/` — from image build, agent can modify and commit
- `.git/` — fresh repo with upstream merge base, agent's branch for tracking its changes

## Dev vs Prod difference

| | Dev | Prod |
|---|---|---|
| Image | `vesta:local` (built locally) | `ghcr.io/elyxlz/vesta:v0.1.x` (CI) |
| `agent-code/` source | copied from local repo | downloaded from release tarball |
| Mounted code | your working tree's `src/vesta/` | release version's `src/vesta/` |
| MEMORY/prompts/skills | from local repo at image build time | from release at image build time |
