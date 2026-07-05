import pathlib as pl

from . import models as vm


def clear_notifications(state: vm.State, file_paths: list[str]) -> None:
    """Drop processed notification files and tell live clients they cleared.

    One owner for the unlink + notification_cleared emit, shared by the message loop (after a turn
    completes) and the restart/stop tools (before an intentional restart, when the turn's
    notification is already handled). notif_id is the file stem, matching the arrival's
    NotificationEvent.notif_id so clients pair the clear with the pending entry."""
    for path_str in file_paths:
        pl.Path(path_str).unlink(missing_ok=True)
        state.event_bus.emit({"type": "notification_cleared", "notif_id": pl.Path(path_str).stem})


def get_memory_path(config: vm.VestaConfig) -> pl.Path:
    return config.agent_dir / "MEMORY.md"


def get_constitution_path(config: vm.VestaConfig) -> pl.Path:
    return config.agent_dir / "constitution.md"


def load_prompt(name: str, config: vm.VestaConfig) -> str | None:
    path = config.core_prompts_dir / f"{name}.md"
    if path.exists():
        return path.read_text()
    return None


def build_restart_context(reason: str, config: vm.VestaConfig, *, extras: list[str] | None = None) -> str:
    # Reasons are stored as "category: detail"; the category is an internal tag (it drives the
    # crash exit-code path), so show only the human detail under a clear restart header.
    detail = reason.split(": ", 1)[1] if ": " in reason else reason
    parts = [f"[System Restart]\nReason: {detail}"]
    if extras:
        parts.extend(extras)
    greeting = load_prompt("restart", config) or ""
    if greeting.strip():
        parts.append(greeting.strip())
    return "\n\n".join(parts)
