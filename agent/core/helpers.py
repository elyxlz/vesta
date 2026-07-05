import pathlib as pl

from . import models as vm


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
    # Reasons are stored as "category: detail"; most categories are internal routing tags, so show
    # only the human detail under a clear restart header. crash/error stay whole: the restart skill
    # branches on a crash boot ("crash -> mention it"), so their marker must survive the render.
    category, _, detail = reason.partition(": ")
    shown = reason if category in ("crash", "error") or not detail else detail
    parts = [f"[System Restart]\nReason: {shown}"]
    if extras:
        parts.extend(extras)
    greeting = load_prompt("restart", config) or ""
    if greeting.strip():
        parts.append(greeting.strip())
    return "\n\n".join(parts)
