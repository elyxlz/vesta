"""Prompt-based migration runner.

Each migration is a markdown file under `agent/core/migrations/`. The file's
stem is the migration name. On boot we queue every unapplied migration as a
system message before the normal greeting; each prompt instructs the agent to
append its own name to `~/agent/data/migrations.applied` once finished, so it
won't run again.

Fresh agents skip migrations entirely: on first start we mark every shipping
migration as applied without running it. Migrations only exist to converge
legacy state. Future migrations added in later images are not pre-marked, so
they still queue when the user updates.
"""

import asyncio
import pathlib as pl

from . import logger
from . import models as vm

APPLIED_FILE_NAME = "migrations.applied"


def _migrations_dir(config: vm.VestaConfig) -> pl.Path:
    return config.agent_dir / "core" / "migrations"


def applied_file(config: vm.VestaConfig) -> pl.Path:
    return config.data_dir / APPLIED_FILE_NAME


def _read_applied(config: vm.VestaConfig) -> set[str]:
    path = applied_file(config)
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


def list_pending(config: vm.VestaConfig) -> list[tuple[str, str]]:
    """Return ``[(name, content), ...]`` for migrations not yet applied, in filename order."""
    migrations_dir = _migrations_dir(config)
    if not migrations_dir.exists():
        return []
    applied = _read_applied(config)
    pending: list[tuple[str, str]] = []
    for path in sorted(migrations_dir.glob("*.md")):
        name = path.stem
        if name in applied:
            continue
        pending.append((name, path.read_text()))
    return pending


async def queue_migrations(queue: asyncio.Queue[tuple[str, bool]], *, config: vm.VestaConfig, first_start: bool = False) -> int:
    """Queue every pending migration as a system message. Returns the count queued. On first start, mark all pending migrations applied without queuing them — the agent is born already converged."""
    pending = list_pending(config)
    if first_start:
        if pending:
            path = applied_file(config)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as f:
                for name, _ in pending:
                    f.write(f"{name}\n")
            logger.startup(f"Pre-marked {len(pending)} migration(s) as applied (fresh agent)")
        return 0
    for name, content in pending:
        prompt = f"[Migration: {name}]\n\n{content.strip()}"
        await queue.put((prompt, False))
        logger.startup(f"Queued migration: {name}")
    return len(pending)
