import pathlib as pl

from . import models as vm


def get_memory_path(config: vm.VestaConfig) -> pl.Path:
    return config.agent_dir / "MEMORY.md"


def load_prompt(name: str, config: vm.VestaConfig) -> str | None:
    agent_path = config.prompts_dir / f"{name}.md"
    if agent_path.exists():
        return agent_path.read_text()
    core_path = config.agent_dir / "core" / "prompts" / f"{name}.md"
    if core_path.exists():
        return core_path.read_text()
    return None


def build_restart_context(reason: str, config: vm.VestaConfig, *, extras: list[str] | None = None) -> str:
    parts = [f"[System: {reason}]"]
    if extras:
        parts.extend(extras)
    greeting = load_prompt("restart", config) or ""
    if greeting.strip():
        parts.append(greeting.strip())
    return "\n\n".join(parts)
