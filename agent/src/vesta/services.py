"""In-memory service registry.

Any process inside the container that needs to be reachable from the
outside registers its name and port here. vestad queries GET /services
to discover them and routes directly, bypassing the agent.
"""

_services: dict[str, int] = {}

RESERVED = {"ws", "history", "services"}


def register(name: str, port: int) -> None:
    if name in RESERVED:
        raise ValueError(f"reserved service name: {name}")
    _services[name] = port


def unregister(name: str) -> None:
    _services.pop(name, None)


def all_services() -> dict[str, int]:
    return dict(_services)
