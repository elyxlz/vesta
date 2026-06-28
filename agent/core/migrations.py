"""Prompt-based migration runner.

Each migration is a markdown file under `agent/core/migrations/`. The file's
stem is the migration name. On boot every unapplied migration is delivered as a
boot turn (see core/main.py collect_boot_turns), processed immediately and
non-interruptibly before the agent takes other work. The runner appends a final
step instructing the agent to call `mark_migration_applied(name)` — authors do
not write it per file — which records it in `state.json`. If the
agent never calls the tool — rate limit, crash, hallucinated success — the
migration runs again on the next boot. Migration prompts must therefore be
idempotent.

Fresh agents skip migrations entirely: on first start we mark every shipping
migration as applied without running it. Migrations only exist to converge
legacy state. Future migrations added in later images are not pre-marked, so
they still queue when the user updates.
"""

import pathlib as pl

from . import logger
from . import models as vm
from . import state_store


def _migrations_dir(config: vm.VestaConfig) -> pl.Path:
    return config.agent_dir / "core" / "migrations"


def list_pending(*, state: vm.State, config: vm.VestaConfig) -> list[tuple[str, str]]:
    """Return ``[(name, content), ...]`` for migrations not yet applied, in filename order."""
    migrations_dir = _migrations_dir(config)
    if not migrations_dir.exists():
        return []
    applied = set(state.persisted.applied_migrations)
    pending: list[tuple[str, str]] = []
    for path in sorted(migrations_dir.glob("*.md")):
        name = path.stem
        if name in applied:
            continue
        pending.append((name, path.read_text()))
    return pending


def pending_migration_turns(*, state: vm.State, config: vm.VestaConfig, first_start: bool = False) -> list[str]:
    """Return one boot-turn prompt body per pending migration, in filename order. On first start, mark every migration applied and return nothing — the agent is born already converged. The agent itself records completion via `mark_migration_applied`; this function does not pre-mark."""
    pending = list_pending(state=state, config=config)
    if first_start:
        if pending:
            state.persisted.applied_migrations.extend(name for name, _ in pending)
            state_store.save_state(state.persisted, config)
            logger.startup(f"Pre-marked {len(pending)} migration(s) as applied (fresh agent)")
        return []
    turns: list[str] = []
    for name, content in pending:
        # Append the completion step here so migration authors never hand-write the name
        # (a typo would mark the wrong name and loop the migration forever). The canonical
        # name is known here, so it is always correct by construction.
        mark_step = f'## Final step\n\nCall `mark_migration_applied` with `name="{name}"`.'
        turns.append(f"[Migration: {name}]\n\n{content.strip()}\n\n{mark_step}")
        logger.startup(f"Queued migration boot turn: {name}")
    return turns
