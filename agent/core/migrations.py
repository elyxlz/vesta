"""Prompt-based migration runner.

Each migration is a markdown file under `agent/core/migrations/`. The file's
stem is the migration name. On boot all unapplied migrations are delivered in
one boot turn (see core/main.py collect_boot_turns), processed immediately and
non-interruptibly before the agent takes other work. The runner appends a final
step instructing the agent to call `mark_migration_applied(name)` — authors do
not write it per file — which records it in `state.json`. If the agent never
calls the tool — rate limit, crash, hallucinated success — the migration runs
again on the next boot. Migration prompts must therefore be idempotent.

Fresh agents skip migrations entirely: on first start we mark every shipping
migration as applied without running it. Migrations only exist to converge
legacy state. Future migrations added in later images are not pre-marked, so
they still queue when the user updates.
"""

import pathlib as pl

from . import config as cfg
from . import logger, state_store
from . import models as vm

MIGRATION_BATCH_INSTRUCTIONS = """[Migration batch]

Process every migration below in filename order before ending this turn. Each
`[Migration: ...]` section is independent. If a migration tells you to STOP or
leave it unmarked, stop only that migration, skip its generated final step, and
continue with the next migration section. Defer any requested `restart_vesta`
call until every migration section has been processed. Do not start later boot
tasks such as upstream sync yourself; they are queued separately after this
batch."""


def _migrations_dir(config: cfg.VestaConfig) -> pl.Path:
    return config.agent_dir / "core" / "migrations"


def list_pending(*, state: vm.State, config: cfg.VestaConfig) -> list[tuple[str, str]]:
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


def pending_migration_turns(*, state: vm.State, config: cfg.VestaConfig, first_start: bool = False) -> list[str]:
    """Return one boot-turn prompt containing every pending migration in filename order.

    On first start, mark every migration applied and return nothing — the agent is born already
    converged. The agent itself records completion via `mark_migration_applied`; this function does
    not pre-mark.
    """
    pending = list_pending(state=state, config=config)
    if first_start:
        if pending:
            state.persisted.applied_migrations.extend(name for name, _ in pending)
            state_store.save_state(state.persisted, config)
            logger.startup(f"Pre-marked {len(pending)} migration(s) as applied (fresh agent)")
        return []
    if not pending:
        return []
    sections: list[str] = []
    for name, content in pending:
        # Append the completion step here so migration authors never hand-write the name
        # (a typo would mark the wrong name and loop the migration forever). The canonical
        # name is known here, so it is always correct by construction.
        mark_step = f'## Final step\n\nCall `mark_migration_applied` with `name="{name}"`.'
        sections.append(f"[Migration: {name}]\n\n{content.strip()}\n\n{mark_step}")
    names = ", ".join(name for name, _ in pending)
    logger.startup(f"Queued migration batch boot turn ({len(pending)}): {names}")
    return [f"{MIGRATION_BATCH_INSTRUCTIONS}\n\n" + "\n\n---\n\n".join(sections)]
