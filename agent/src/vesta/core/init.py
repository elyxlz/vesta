import os
import pathlib as pl
import shutil

import vesta.models as vm
from vesta import logger

def get_memory_path(config: vm.VestaConfig) -> pl.Path:
    return config.memory_dir / "MEMORY.md"


def _discover_skills(config: vm.VestaConfig) -> dict[str, pl.Path]:
    skills_dir = config.skills_dir
    return {d.name: d for d in sorted(skills_dir.iterdir()) if d.is_dir() and (d / "SKILL.md").exists()}


def _replace_placeholders(path: pl.Path, config: vm.VestaConfig) -> bool:
    content = path.read_text()
    original = content
    name = config.agent_name
    content = content.replace("{install_root}", str(config.install_root))
    content = content.replace("{agent_name_upper}", name.upper())
    content = content.replace("{agent_name}", name)
    if content != original:
        path.write_text(content)
        return True
    return False


def init_skills(config: vm.VestaConfig) -> None:
    for skill_name, skill_dir in _discover_skills(config).items():
        skill_md = skill_dir / "SKILL.md"
        if _replace_placeholders(skill_md, config):
            logger.init(f"Initialized skill: {skill_name}")

        scripts_dir = skill_dir / "scripts"
        if scripts_dir.is_dir():
            for script in scripts_dir.iterdir():
                if script.is_file():
                    script.chmod(0o755)


def init_main_memory(config: vm.VestaConfig) -> bool:
    """Initialize main memory placeholders. Returns True if this is a first start."""
    memory_path = get_memory_path(config)
    if not memory_path.exists():
        return True
    content = memory_path.read_text()
    first_start = '[Unknown - need to ask]' in content
    if _replace_placeholders(memory_path, config):
        logger.init("Initialized placeholders in MEMORY.md")
    return first_start


def init_prompts(config: vm.VestaConfig) -> None:
    config.prompts_dir.mkdir(parents=True, exist_ok=True)


def load_prompt(name: str, config: vm.VestaConfig) -> str | None:
    path = config.prompts_dir / f"{name}.md"
    if path.exists():
        return path.read_text()
    return None


def build_restart_context(reason: str, config: vm.VestaConfig, *, extras: list[str] | None = None) -> str:
    parts = [f"[System: {reason}]"]
    if extras:
        parts.extend(extras)
    greeting = load_prompt("restart", config) or ""
    if greeting.strip():
        parts.append(greeting.strip())
    return "\n\n".join(parts)


def init_skills_symlink(config: vm.VestaConfig) -> None:
    target = config.state_dir / ".claude" / "skills"
    target.parent.mkdir(parents=True, exist_ok=True)
    path = str(target)
    if os.path.islink(path) or os.path.lexists(path):
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.unlink(path)
    target.symlink_to(config.skills_dir)
