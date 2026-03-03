import os
import pathlib as pl
import shutil

import vesta.models as vm
from vesta import logger

_INSTALL_ROOT_PLACEHOLDER = "{install_root}"


def get_memory_path(config: vm.VestaConfig) -> pl.Path:
    return config.memory_dir / "MEMORY.md"


def _discover_skills(config: vm.VestaConfig) -> dict[str, pl.Path]:
    skills_dir = config.skills_dir
    return {d.name: d for d in sorted(skills_dir.iterdir()) if d.is_dir() and (d / "SKILL.md").exists()}


def _replace_placeholder_in_file(path: pl.Path, install_root: str) -> bool:
    """Replace {install_root} placeholder in a file if still present. Returns True if replaced."""
    content = path.read_text()
    if _INSTALL_ROOT_PLACEHOLDER in content:
        path.write_text(content.replace(_INSTALL_ROOT_PLACEHOLDER, install_root))
        return True
    return False


def init_skills(config: vm.VestaConfig) -> None:
    install_root = str(config.install_root)
    for skill_name, skill_dir in _discover_skills(config).items():
        skill_md = skill_dir / "SKILL.md"
        if _replace_placeholder_in_file(skill_md, install_root):
            logger.init(f"Initialized skill: {skill_name}")

        # Ensure scripts are executable
        scripts_dir = skill_dir / "scripts"
        if scripts_dir.is_dir():
            for script in scripts_dir.iterdir():
                if script.is_file():
                    script.chmod(0o755)


def is_first_start(config: vm.VestaConfig) -> bool:
    memory_path = get_memory_path(config)
    if not memory_path.exists():
        return True
    content = memory_path.read_text()
    return '[Unknown - need to ask]' in content


def init_main_memory(config: vm.VestaConfig) -> None:
    memory_path = get_memory_path(config)
    if not memory_path.exists():
        return
    install_root = str(config.install_root)
    if _replace_placeholder_in_file(memory_path, install_root):
        logger.init("Replaced install_root placeholder in MEMORY.md")


def init_prompts(config: vm.VestaConfig) -> None:
    config.prompts_dir.mkdir(parents=True, exist_ok=True)


def load_prompt(name: str, config: vm.VestaConfig) -> str | None:
    path = config.prompts_dir / f"{name}.md"
    if path.exists():
        return path.read_text()
    return None


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
