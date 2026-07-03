"""Upgrade-driven workspace sync trigger.

A vestad upgrade re-extracts the core mount, so the running core version (read from
core/pyproject.toml) changes across the restart. This module turns that signal into a
boot turn: when the persisted `last_synced_version` doesn't match the running version,
the agent is told to rebase its workspace onto this version's published snapshot
(`agent-v<version>` on the agent branch) and record completion via the
`mark_workspace_synced` tool. Unmarked (failed, crashed, forgotten) turns re-fire on
every boot until the sync lands — the flow itself is idempotent.

Fresh agents pre-mark the current version without a turn (the image is already
current), the same pattern migrations use. An unreadable version never fires and never
marks: no churn on a broken pyproject.
"""

import tomllib

from . import logger
from . import models as vm
from . import state_store

UNKNOWN_VERSION = "unknown"


def vesta_version(config: vm.VestaConfig) -> str:
    """Version of the code actually running, read from core/pyproject.toml (re-extracted on
    upgrade, so it tracks the running core). Best-effort: never raises over a version label."""
    pyproject = config.agent_dir / "core" / "pyproject.toml"
    if not pyproject.exists():
        return UNKNOWN_VERSION
    try:
        return tomllib.loads(pyproject.read_text())["project"]["version"]
    except (tomllib.TOMLDecodeError, KeyError, OSError) as e:
        logger.init(f"could not read version: {e}")
        return UNKNOWN_VERSION


def workspace_sync_turn(*, state: vm.State, config: vm.VestaConfig, first_start: bool) -> str | None:
    """Boot-turn body telling the agent to sync onto this version's snapshot, or None.

    First start pre-marks the running version (fresh image is already current). An
    unknown version is never acted on. Any mismatch — including an absent marker on a
    legacy agent, and downgrades — fires the turn."""
    running = vesta_version(config)
    if running == UNKNOWN_VERSION:
        return None
    if first_start:
        state.persisted.last_synced_version = running
        state_store.save_state(state.persisted, config)
        return None
    if state.persisted.last_synced_version == running:
        return None
    logger.startup(f"Queued workspace-sync boot turn: {state.persisted.last_synced_version} -> {running}")
    return (
        "[Workspace sync]\n\n"
        f"Vesta was upgraded (now v{running}). Read `~/agent/core/skills/workspace-sync/SKILL.md` "
        f"and follow it to bring your home files up to date with this version: rebase your changes "
        f"onto `agent-v{running}`, resolving any conflicts. Then call `mark_workspace_synced`. "
        "If the rebase brought changes, call `restart_vesta` afterward so updated skills load; "
        "if it was a no-op, no restart is needed. If it fails, tell the user what blocked it."
    )
