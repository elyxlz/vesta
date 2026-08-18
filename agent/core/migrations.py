"""Prompt-based migration runner.

Each migration is a markdown file under `agent/core/migrations/`. The file's
stem is the migration name. Migrations default to the after-sync phase; authors
can select the before-sync phase with Markdown frontmatter (see
core/main.py collect_boot_turns). Pending before-sync migrations form a boot
barrier and restart into sync; pending after-sync migrations are delivered
after the sync turn. An after-sync migration can declare `interruptible: true`
in its frontmatter (rejected on before-sync migrations): interruptible
migrations run as a second batch after the non-interruptible batch, and user
messages may preempt that batch mid-turn, with unmarked migrations re-running
on the next boot. The runner appends a final step instructing the agent to
call `mark_migration_applied(name)` — authors do not write it per file — which
records it in `state.json`. If the agent never calls the tool — rate limit,
crash, hallucinated success — the migration runs again on the next boot.
Migration prompts must therefore be idempotent.

A migration that renames or removes a command must sweep recurring reminder
bodies as well as the source tree. A recurring reminder's message is an
instruction the agent follows when it fires, so it is executable prose that no
grep of `~/agent` can reach: it lives in the reminders store, and a stale command
in one surfaces only when it fires, which is the worst moment to discover it.

Fresh agents skip migrations entirely: on first start we mark every shipping
migration as applied without running it. Migrations only exist to converge
legacy state. Future migrations added in later images are not pre-marked, so
they still queue when the user updates.
"""

import pathlib as pl
from dataclasses import dataclass
from enum import StrEnum

from . import config as cfg
from . import logger, state_store
from . import models as vm


class MigrationPhase(StrEnum):
    BEFORE_SYNC = "before_sync"
    AFTER_SYNC = "after_sync"


@dataclass(frozen=True)
class Migration:
    name: str
    content: str
    phase: MigrationPhase
    interruptible: bool = False


MIGRATION_BATCH_INSTRUCTIONS = """[Migration batch]

Process every migration below in filename order before ending this turn. Each
`[Migration: ...]` section is independent. If a migration tells you to STOP or
leave it unmarked, stop only that migration, skip its generated final step, and
continue with the next migration section. Defer any requested `restart_vesta`
call until every migration section has been processed. Do not start other boot
tasks yourself; core queues them separately."""

BEFORE_SYNC_BATCH_INSTRUCTIONS = """

This is the before-sync migration phase. Upstream sync is blocked until every
migration in this batch is applied. After processing the batch, if you marked at
least one migration applied, call `restart_vesta` once. The next boot will retry
anything left unmarked and will only proceed to upstream sync when this phase is
clear."""


def _migrations_dir(config: cfg.VestaConfig) -> pl.Path:
    return config.agent_dir / "core" / "migrations"


def _parse_migration(path: pl.Path) -> Migration:
    """Read one migration, validating and removing its optional phase frontmatter."""
    text = path.read_text()
    phase = MigrationPhase.AFTER_SYNC
    interruptible = False
    if text.startswith("---\n"):
        frontmatter, separator, content = text[4:].partition("\n---\n")
        if not separator:
            raise ValueError(f"{path}: migration frontmatter has no closing ---")
        fields: dict[str, str] = {}
        for line in frontmatter.splitlines():
            if not line.strip():
                continue
            key, field_separator, value = line.partition(":")
            if not field_separator or not key.strip() or not value.strip():
                raise ValueError(f"{path}: invalid migration frontmatter line: {line!r}")
            fields[key.strip()] = value.strip()
        unknown = set(fields) - {"migration_phase", "interruptible"}
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"{path}: unknown migration frontmatter field(s): {names}")
        if "migration_phase" in fields:
            try:
                phase = MigrationPhase(fields["migration_phase"])
            except ValueError as error:
                allowed = ", ".join(item.value for item in MigrationPhase)
                raise ValueError(f"{path}: migration_phase must be one of: {allowed}") from error
        if "interruptible" in fields:
            if phase is MigrationPhase.BEFORE_SYNC:
                raise ValueError(f"{path}: interruptible is not allowed on a before_sync migration")
            if fields["interruptible"] not in ("true", "false"):
                raise ValueError(f"{path}: interruptible must be true or false")
            interruptible = fields["interruptible"] == "true"
        text = content
    return Migration(name=path.stem, content=text, phase=phase, interruptible=interruptible)


def list_pending(*, state: vm.State, config: cfg.VestaConfig) -> list[Migration]:
    """Return unapplied migrations in filename order, with their declared sync phase."""
    migrations_dir = _migrations_dir(config)
    if not migrations_dir.exists():
        return []
    applied = set(state.persisted.applied_migrations)
    pending: list[Migration] = []
    for path in sorted(migrations_dir.glob("*.md")):
        if path.stem in applied:
            continue
        pending.append(_parse_migration(path))
    return pending


def _batch_turn(batch: list[Migration], *, phase: MigrationPhase, interruptible: bool) -> vm.QueuedTurn:
    sections: list[str] = []
    for migration in batch:
        # Append the completion step here so migration authors never hand-write the name
        # (a typo would mark the wrong name and loop the migration forever). The canonical
        # name is known here, so it is always correct by construction.
        mark_step = f'## Final step\n\nCall `mark_migration_applied` with `name="{migration.name}"`.'
        sections.append(f"[Migration: {migration.name}]\n\n{migration.content.strip()}\n\n{mark_step}")
    instructions = MIGRATION_BATCH_INSTRUCTIONS
    if phase is MigrationPhase.BEFORE_SYNC:
        instructions += BEFORE_SYNC_BATCH_INSTRUCTIONS
    return vm.QueuedTurn(f"{instructions}\n\n" + "\n\n---\n\n".join(sections), False, [], interruptible=interruptible)


def _migration_turns(
    *,
    pending: list[Migration],
    state: vm.State,
    config: cfg.VestaConfig,
    first_start: bool,
    phase: MigrationPhase,
) -> list[vm.QueuedTurn]:
    if first_start:
        if pending:
            state.persisted.applied_migrations.extend(migration.name for migration in pending)
            state_store.save_state(state.persisted, config)
            logger.startup(f"Pre-marked {len(pending)} migration(s) as applied (fresh agent)")
        return []
    turns: list[vm.QueuedTurn] = []
    for interruptible in (False, True):
        batch = [migration for migration in pending if migration.interruptible is interruptible]
        if not batch:
            continue
        names = ", ".join(migration.name for migration in batch)
        label = "interruptible " if interruptible else ""
        logger.startup(f"Queued {phase.value} {label}migration batch boot turn ({len(batch)}): {names}")
        turns.append(_batch_turn(batch, phase=phase, interruptible=interruptible))
    return turns


def _pending_for(*, state: vm.State, config: cfg.VestaConfig, first_start: bool, phase: MigrationPhase) -> list[Migration]:
    """Pending migrations of one phase, or the complete shipping set on first start: a fresh agent
    pre-marks every phase whichever getter runs first, so the two are order-independent."""
    pending = list_pending(state=state, config=config)
    if first_start:
        return pending
    return [migration for migration in pending if migration.phase is phase]


def before_sync_migration_turns(*, state: vm.State, config: cfg.VestaConfig, first_start: bool = False) -> list[vm.QueuedTurn]:
    """Return pending before-sync migrations as an exclusive boot barrier."""
    return _migration_turns(
        pending=_pending_for(state=state, config=config, first_start=first_start, phase=MigrationPhase.BEFORE_SYNC),
        state=state,
        config=config,
        first_start=first_start,
        phase=MigrationPhase.BEFORE_SYNC,
    )


def after_sync_migration_turns(*, state: vm.State, config: cfg.VestaConfig, first_start: bool = False) -> list[vm.QueuedTurn]:
    """Return pending after-sync migrations as filename-ordered boot turns, the non-interruptible batch first.

    These can rely on the running version's stock files being present. The agent itself records
    completion on upgrade boots.
    """
    return _migration_turns(
        pending=_pending_for(state=state, config=config, first_start=first_start, phase=MigrationPhase.AFTER_SYNC),
        state=state,
        config=config,
        first_start=first_start,
        phase=MigrationPhase.AFTER_SYNC,
    )
