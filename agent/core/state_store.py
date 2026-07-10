"""Single-file persistent state for the agent.

All boot-time and cross-restart markers live in `~/agent/data/state.json`. Loaded once
at boot, mutated in place via the `PersistedState` field on `vm.State`, and saved
immediately via `save_state` after every mutation. Writes are atomic (tmp + rename).
"""

import datetime as dt
import os
import pathlib as pl

import pydantic as pyd

from . import logger
from . import config as cfg
from .events import EVENTS_DB_FILENAME

STATE_FILENAME = "state.json"


def atomic_write_text(path: pl.Path, text: str) -> None:
    """Write text to path atomically: write a sibling temp file, then rename over the target.

    The single owner of the tmp-write + os.replace recipe (state.json, the notification interrupt
    rules store, ...) so durability changes live in one place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


class PersistedState(pyd.BaseModel):
    first_start_done: bool = False
    last_restart_reason: str | None = None
    last_dreamer_run: dt.datetime | None = None
    # A generic turn delivered once on the next boot (set by the compaction drain for a restart
    # follow-up), then cleared. Only read at boot, so it cannot be read early or strand.
    pending_boot_message: str | None = None
    session_id: str | None = None
    applied_migrations: list[str] = pyd.Field(default_factory=list)
    last_synced_version: str | None = None


def state_path(config: cfg.VestaConfig) -> pl.Path:
    return config.data_dir / STATE_FILENAME


PENDING_REASON_FILENAME = "pending_restart_reason"


def pending_reason_path(config: cfg.VestaConfig) -> pl.Path:
    return config.data_dir / PENDING_REASON_FILENAME


def take_pending_reason(config: cfg.VestaConfig) -> str | None:
    """Read + delete the one-shot restart-reason inbox vestad may have written before this boot.

    The file is transport, not storage: it is drained into last_restart_reason and removed so it
    never re-fires on a later boot. Returns the stripped reason, or None if absent/empty."""
    path = pending_reason_path(config)
    if not path.exists():
        return None
    reason = path.read_text(encoding="utf-8").strip()
    path.unlink(missing_ok=True)
    return reason or None


def load_state(config: cfg.VestaConfig) -> PersistedState:
    path = state_path(config)
    if path.exists():
        try:
            return PersistedState.model_validate_json(path.read_text())
        except (pyd.ValidationError, ValueError, OSError) as e:
            # Don't crash-loop the container on a corrupt or schema-incompatible state.json —
            # log and start fresh. A veteran agent (events.db already exists) must not
            # re-onboard or pre-mark migrations on top of months of memory: corroborate against
            # the data dir and mark it a fresh boot only if there is truly no prior history.
            veteran = (config.data_dir / EVENTS_DB_FILENAME).exists()
            logger.error(
                f"state.json unparseable ({type(e).__name__}: {e}) — starting fresh"
                + (" (events.db present: session_id lost, migrations will re-run)" if veteran else "")
            )
            return PersistedState(first_start_done=veteran)
    state = PersistedState()
    save_state(state, config)
    return state


def save_state(state: PersistedState, config: cfg.VestaConfig) -> None:
    atomic_write_text(state_path(config), state.model_dump_json())
