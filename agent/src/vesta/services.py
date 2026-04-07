"""Persistent service registry.

Any process inside the container that needs to be reachable from the
outside registers its name and port here. vestad queries GET /services
to discover them and routes directly, bypassing the agent.

State is persisted to ~/.services.json so registrations survive restarts.
"""

import json
import logging
import os
import pathlib as pl

log = logging.getLogger(__name__)

_SERVICES_FILE = pl.Path.home() / ".services.json"

_services: dict[str, int] = {}

RESERVED = {"ws", "history", "services"}


def _load() -> None:
    global _services
    try:
        _services = json.loads(_SERVICES_FILE.read_text())
    except FileNotFoundError:
        _services = {}
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load %s: %s", _SERVICES_FILE, exc)
        _services = {}


def _save() -> None:
    tmp = _SERVICES_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_services, indent=2) + "\n")
    os.replace(tmp, _SERVICES_FILE)


def register(name: str, port: int) -> None:
    if name in RESERVED:
        raise ValueError(f"reserved service name: {name}")
    _services[name] = port
    _save()


def unregister(name: str) -> None:
    _services.pop(name, None)
    _save()


def all_services() -> dict[str, int]:
    return dict(_services)


# Load on import
_load()
