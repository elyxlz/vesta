"""Single-file persistent state for the agent.

All boot-time and cross-restart markers live in `~/agent/data/state.json`. Loaded once
at boot, mutated in place via the `PersistedState` field on `vm.State`, and saved
immediately via `save_state` after every mutation. Writes are atomic (tmp + rename).

On first boot under this code path, `load_state` imports any legacy marker files
(`first_start_done`, `restart_reason`, `last_dreamer_run`, `show_dreamer_summary`,
`session_id`, `migrations.applied`) into the new schema and removes them.
"""

import datetime as dt
import os
import pathlib as pl

import pydantic as pyd

from . import logger
from . import config as cfg

STATE_FILENAME = "state.json"

LEGACY_FILES = (
    "first_start_done",
    "restart_reason",
    "last_dreamer_run",
    "show_dreamer_summary",
    "session_id",
    "migrations.applied",
)


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
    state = _import_legacy(config)
    save_state(state, config)
    _remove_legacy_files(config)
    return state


def save_state(state: PersistedState, config: cfg.VestaConfig) -> None:
    path = state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(state.model_dump_json())
    os.replace(tmp, path)


def _import_legacy(config: cfg.VestaConfig) -> PersistedState:
    d = config.data_dir
    legacy = PersistedState(
        first_start_done=(d / "first_start_done").exists(),
        last_restart_reason=_read_text_or_none(d / "restart_reason"),
        last_dreamer_run=_parse_iso_or_none(d / "last_dreamer_run"),
        show_dreamer_summary=(d / "show_dreamer_summary").exists(),
        session_id=_read_text_or_none(d / "session_id"),
        applied_migrations=_read_lines(d / "migrations.applied"),
    )
    if any(
        [
            legacy.first_start_done,
            legacy.last_restart_reason,
            legacy.last_dreamer_run,
            legacy.show_dreamer_summary,
            legacy.session_id,
            legacy.applied_migrations,
        ]
    ):
        logger.startup("Imported legacy marker files into state.json")
    return legacy


def _read_text_or_none(path: pl.Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text().strip() or None


def _parse_iso_or_none(path: pl.Path) -> dt.datetime | None:
    raw = _read_text_or_none(path)
    if raw is None:
        return None
    return dt.datetime.fromisoformat(raw)


def _read_lines(path: pl.Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def _remove_legacy_files(config: cfg.VestaConfig) -> None:
    for name in LEGACY_FILES:
        (config.data_dir / name).unlink(missing_ok=True)
