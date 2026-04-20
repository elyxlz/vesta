---
name: declutter
description: This skill should be used when the user asks about "cleanup", "disk space", "clean up", "free space", "cache", "declutter", or wants to reclaim storage in their vesta agent container.
---

# Cleanup: Disk Space Utility

Scans the vesta container for cleanable items and optionally deletes them. Safe by default: always shows what will be removed before doing anything.

## Two-Tier System

Targets are split into two tiers:

- **Tier 1: Auto-clean**: safe items that regenerate automatically without any network access (Python bytecode, old logs, stale `/tmp` files, build artifacts). Cleaned by `--clean`.
- **Tier 2: Report-only**: caches that will re-download on next use (pip, uv, npm, Go build cache, HuggingFace models, Playwright browsers). Shown in dry-run reports with last-access time. Only cleaned by `--clean-all`.

## Commands

```bash
# Show what can be cleaned (dry-run, safe: no deletions)
python3 ~/agent/skills/declutter/scripts/cleanup.py

# Clean tier-1 only (safe: items regenerate automatically)
python3 ~/agent/skills/declutter/scripts/cleanup.py --clean

# Clean everything including tier-2 caches
python3 ~/agent/skills/declutter/scripts/cleanup.py --clean-all

# Clean specific categories only
python3 ~/agent/skills/declutter/scripts/cleanup.py --clean --target pyc logs

# List available targets
python3 ~/agent/skills/declutter/scripts/cleanup.py --list-targets
```

## Cleanup Targets

### Tier 1: Auto-clean (`--clean`)

| Target | Path | Notes |
|--------|------|-------|
| `pyc` | `~/agent/**/*.pyc`, `__pycache__/` | Compiled Python bytecode: safe, Python regenerates automatically |
| `logs` | `~/agent/logs/` | Rotated/old log files: keeps the current (most recent) log per prefix |
| `tmp` | `/tmp/` | Stale files older than 24 hours |
| `build-artifacts` | Python `build/`, `dist/` (only when sibling `pyproject.toml`/`setup.py` exists), plus `*.egg-info/` under `~/agent/skills/` | Excludes `node_modules/`, `.venv/`, and Node-based skills so vite/tsup `dist/` and packaged `dist/` inside npm packages are never touched |

### Tier 2: Report-only (`--clean-all` required)

| Target | Path | Notes |
|--------|------|-------|
| `pip-cache` | `~/.cache/pip/` | pip wheel/HTTP cache: safe to delete, pip re-downloads as needed |
| `uv-cache` | `~/.cache/uv/` | uv package cache: safe to delete, uv re-downloads as needed |
| `go-build` | `~/.cache/go-build/` | Go build cache: safe to delete, Go rebuilds as needed |
| `npm-cache` | `~/.npm/` | npm package cache: safe to delete, npm re-downloads as needed |
| `huggingface` | `~/.cache/huggingface/` | HuggingFace model/dataset cache: **models must be re-downloaded** |
| `playwright` | `~/.cache/ms-playwright/` | Playwright browser binaries: **browser automation breaks until `playwright install` is re-run** |

## Warnings

- **`huggingface`**: Deleting this means any ML models stored there must be re-downloaded from HuggingFace Hub. This can be large (GBs) and slow on metered connections.
- **`playwright`**: Deleting browser binaries breaks any skill that uses browser automation. Run `playwright install` to restore.
- Dry-run mode shows last-access time for tier-2 cache directories so you can see what's stale before deciding.

## Notes

- Default mode is `--dry-run`: always safe to run for a disk usage report.
- Dry-run output is clearly labelled: "Auto-clean" section and "Report only (caches)" section.
- Sizes are calculated before any deletion.
- The script uses only Python stdlib + pathlib: no shell commands, no extra dependencies.
