import os
import pathlib as pl
import shutil

import vesta.models as vm
from vesta import logger

_TEMPLATES_DIR = pl.Path(__file__).parent.parent / "templates"


def get_memory_path(config: vm.VestaConfig) -> pl.Path:
    return config.memory_dir / "MEMORY.md"


def load_memory_template() -> str:
    return (_TEMPLATES_DIR / "MEMORY.md").read_text()


def _discover_skill_templates() -> dict[str, pl.Path]:
    skills_dir = _TEMPLATES_DIR / "skills"
    return {d.name: d for d in sorted(skills_dir.iterdir()) if d.is_dir() and (d / "SKILL.md").exists()}


def init_skills(config: vm.VestaConfig) -> None:
    for skill_name, template_dir in _discover_skill_templates().items():
        skill_dir = config.skills_dir / skill_name
        if (skill_dir / "SKILL.md").exists():
            continue

        skill_dir.mkdir(parents=True, exist_ok=True)

        content = (template_dir / "SKILL.md").read_text()
        (skill_dir / "SKILL.md").write_text(content.replace("{install_root}", str(config.install_root)))

        scripts_src = template_dir / "scripts"
        if scripts_src.is_dir():
            scripts_dst = skill_dir / "scripts"
            scripts_dst.mkdir(parents=True, exist_ok=True)
            for script in scripts_src.iterdir():
                if script.is_file():
                    shutil.copy2(script, scripts_dst / script.name)
                    (scripts_dst / script.name).chmod(0o755)

        logger.init(f"Initialized skill: {skill_name}")


def is_first_start(config: vm.VestaConfig) -> bool:
    return not get_memory_path(config).exists()


def init_main_memory(config: vm.VestaConfig) -> None:
    memory_path = get_memory_path(config)
    if not memory_path.exists():
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        name = config.agent_name
        template = (
            load_memory_template()
            .replace("{install_root}", str(config.install_root))
            .replace("{agent_name_upper}", name.upper())
            .replace("{agent_name}", name)
        )
        memory_path.write_text(template)
        logger.init(f"Initialized main memory ({len(template)} chars)")


def init_prompts(config: vm.VestaConfig) -> None:
    prompts_dir = config.prompts_dir
    prompts_dir.mkdir(parents=True, exist_ok=True)
    for src in (_TEMPLATES_DIR / "prompts").glob("*.md"):
        dest = prompts_dir / src.name
        if not dest.exists():
            shutil.copy2(src, dest)
            logger.init(f"Initialized prompt: {src.stem}")


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
