---
name: upstream-sync
description: Sync local agent code with upstream vesta: updates, merges, conflicts.
---

# Upstream Sync

Keep your branch current with upstream. To push changes back, see [upstream-pr](../upstream-pr/SKILL.md).

- **`scripts/status.sh`** (read-only): how far behind/ahead of `$VESTA_UPSTREAM_REF` you are, what's incoming, and your own changes vs upstream.
- **`scripts/sync.sh`**: pull upstream in. Does the whole job (checkpoint, narrow cone, fetch, merge, refresh the skills registry). It only stops for a real content conflict: it exits 2 and lists the files, resolve them and run it again to finish.

## Conflicts

Integrate, don't just pick a side: rewrite the file so both changes survive. For `agent/MEMORY.md`, keep your accumulated knowledge and adopt upstream's structure. Then `git -C ~ add <file>` and re-run `sync.sh`.

## Yours vs vestad's

You own `agent/skills/`, `agent/MEMORY.md`, `agent/.gitignore`. Only installed skills are on disk; `agent/skills/index.json` always lists the full registry, so `skills-install` can pull any of them.

`agent/core/`, `agent/pyproject.toml`, `agent/uv.lock` are vestad's engine: read-only mounts, gitignored, never tracked or contributed. They update with the container image, not through git.

First-time only: run [SETUP.md](SETUP.md) once, then `sync.sh` from then on.

## Troubleshooting

Old agents with a messed-up git setup (broad sparse cone, committed core, unrelated history) self-heal on the next `sync.sh`: it narrows the cone, untracks the vestad-managed paths, and merges. Expect real conflicts on the first run for owned files you'd edited, resolve and re-run.

- **First sync hits many conflicts:** normal for a legacy/unrelated-history agent. They're only on files you actually changed; resolve each and re-run.
- **Sync won't start ("not a git repository", empty `git status`, or tree looks stripped):** the workspace was never initialised or got wiped. Re-run [SETUP.md](SETUP.md), then `sync.sh`.
