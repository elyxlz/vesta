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

STATE_FILENAME = "state.json"


class PersistedState(pyd.BaseModel):
    first_start_done: bool = False
    last_restart_reason: str | None = None
    last_dreamer_run: dt.datetime | None = None
    show_dreamer_summary: bool = False
    session_id: str | None = None
    applied_migrations: list[str] = pyd.Field(default_factory=list)
    # Last-known provider-auth state. Survives container restart so a runtime
    # 401 (e.g., revoked token) stays visible after dreamer-restart rather than
    # the agent quietly booting back into "authenticated" until the next 401.
    # Source of truth: Provider re-derives on boot from disk if this is None.
    provider_auth_state: str | None = None


def state_path(config: cfg.VestaConfig) -> pl.Path:
    return config.data_dir / STATE_FILENAME


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
    path = state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(state.model_dump_json())
    os.replace(tmp, path)
