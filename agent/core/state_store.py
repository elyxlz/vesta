"""Single-file persistent state for the agent.

All boot-time and cross-restart markers live in `~/agent/data/state.json`. Loaded once
at boot, mutated in place via the `PersistedState` field on `vm.State`, and saved
immediately after every mutation: `save_state` from sync code (boot, done-callbacks,
cancellation handlers), `save_state_async` from coroutines. Writes are atomic and
durable (cfg.atomic_write_text: tmp + fsync + rename).
"""

import asyncio
import datetime as dt
import pathlib as pl

import pydantic as pyd

from . import logger
from . import config as cfg

STATE_FILENAME = "state.json"


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
            # Don't crash-loop the container on a corrupt or schema-incompatible
            # state.json — log and start fresh; first-start will re-run.
            logger.error(f"state.json unparseable ({type(e).__name__}: {e}) — starting fresh")
            return PersistedState()
    state = PersistedState()
    save_state(state, config)
    return state


def save_state(state: PersistedState, config: cfg.VestaConfig) -> None:
    cfg.atomic_write_text(state_path(config), state.model_dump_json())


async def save_state_async(state: PersistedState, config: cfg.VestaConfig) -> None:
    """save_state for coroutines: snapshot the JSON on the event loop (a consistent view of the
    mutable state), then run the fsync-ing write in a worker thread so it never stalls the loop."""
    payload = state.model_dump_json()
    await asyncio.to_thread(cfg.atomic_write_text, state_path(config), payload)
