"""Tiny on-disk session store for the onboard flow.

The agent drives onboarding across many separate CLI invocations, so the buyer's
verified session (and a little server/agent context) has to persist between them.
It is keyed by the buyer's email and lives in a 0600 file under the user's config
dir. This is the buyer's OWN session — obtained when they read their OTP back — so
from here on the CLI acts AS the buyer (the conduit model); the per-VM api_key is
never involved and never stored. The entry is cleared once the agent is connected.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_STATE_DIR = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "vesta-onboard"
_STATE_FILE = _STATE_DIR / "sessions.json"


def _key(email: str) -> str:
    return email.strip().lower()


def _read_all() -> dict[str, Any]:
    try:
        return json.loads(_STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _write_all(data: dict[str, Any]) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Write 0600 (it holds a session token) to a temp file, then atomically
    # os.replace — so an overlapping CLI invocation never reads a half-written
    # file (the read-modify-write itself is still unsynchronized; the SKILL keeps
    # onboards one-at-a-time, and atomic replace prevents corruption).
    tmp = _STATE_FILE.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, _STATE_FILE)


def load(email: str) -> dict[str, Any]:
    """Return the stored onboarding context for ``email`` (``{}`` if none)."""
    return _read_all().get(_key(email), {})


def update(email: str, **fields: Any) -> dict[str, Any]:
    """Merge ``fields`` into ``email``'s stored context and persist it."""
    data = _read_all()
    entry = data.get(_key(email), {})
    entry.update({k: v for k, v in fields.items() if v is not None})
    data[_key(email)] = entry
    _write_all(data)
    return entry


def clear(email: str) -> None:
    """Forget everything stored for ``email`` (call once onboarding completes)."""
    data = _read_all()
    if data.pop(_key(email), None) is not None:
        _write_all(data)


def forget(email: str, *keys: str) -> None:
    """Drop specific keys from ``email``'s context (e.g. a consumed OAuth nonce)."""
    data = _read_all()
    entry = data.get(_key(email))
    if not entry:
        return
    if any(entry.pop(k, None) is not None for k in keys):
        data[_key(email)] = entry
        _write_all(data)


def token_for(email: str) -> str | None:
    """The buyer's session token, or None if they haven't verified yet."""
    return load(email).get("token")
