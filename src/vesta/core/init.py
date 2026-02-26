import pathlib as pl

import vesta.models as vm
from vesta import logger
from vesta.templates.main import MEMORY_TEMPLATE as MAIN_MEMORY_TEMPLATE
from vesta.templates.prompts import ALL as PROMPT_TEMPLATES
from vesta.templates.skills import (
    browser,
    google as google_skill,
    keeper,
    microsoft,
    onedrive,
    reminders,
    report_writer,
    todos,
    what_day,
    whatsapp,
)

type SkillTemplate = dict[str, str | dict[str, str]]


def get_memory_path(config: vm.VestaConfig) -> pl.Path:
    return config.memory_dir / "MEMORY.md"


def load_memory_template(name: str) -> str:
    if name == "main":
        return MAIN_MEMORY_TEMPLATE
    raise ValueError(f"Unknown memory template: {name}")


def get_skill_templates() -> dict[str, SkillTemplate]:
    return {
        "microsoft": {"skill_md": microsoft.SKILL_MD, "scripts": microsoft.SCRIPTS},
        "google": {"skill_md": google_skill.SKILL_MD, "scripts": google_skill.SCRIPTS},
        "browser": {"skill_md": browser.SKILL_MD, "scripts": browser.SCRIPTS},
        "report-writer": {"skill_md": report_writer.SKILL_MD, "scripts": report_writer.SCRIPTS},
        "what-day": {"skill_md": what_day.SKILL_MD, "scripts": what_day.SCRIPTS},
        "whatsapp": {"skill_md": whatsapp.SKILL_MD, "scripts": whatsapp.SCRIPTS},
        "reminders": {"skill_md": reminders.SKILL_MD, "scripts": reminders.SCRIPTS},
        "todos": {"skill_md": todos.SKILL_MD, "scripts": todos.SCRIPTS},
        "onedrive": {"skill_md": onedrive.SKILL_MD, "scripts": onedrive.SCRIPTS},
        "keeper": {"skill_md": keeper.SKILL_MD, "scripts": keeper.SCRIPTS},
    }


def init_skills(config: vm.VestaConfig) -> None:
    skills_dir = config.skills_dir
    skill_templates = get_skill_templates()

    for skill_name, skill_data in skill_templates.items():
        skill_dir = skills_dir / skill_name
        skill_md_path = skill_dir / "SKILL.md"

        if skill_md_path.exists():
            continue

        skill_dir.mkdir(parents=True, exist_ok=True)

        skill_md_content = skill_data["skill_md"]
        if isinstance(skill_md_content, str):
            skill_md_content = skill_md_content.replace("{install_root}", str(config.install_root))
            skill_md_path.write_text(skill_md_content)

        scripts = skill_data["scripts"]
        if isinstance(scripts, dict) and scripts:
            scripts_dir = skill_dir / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            for script_name, script_content in scripts.items():
                script_path = scripts_dir / script_name
                script_path.write_text(script_content)
                script_path.chmod(0o755)

        logger.init(f"Initialized skill: {skill_name}")


def is_first_start(config: vm.VestaConfig) -> bool:
    return not get_memory_path(config).exists()


def init_main_memory(config: vm.VestaConfig) -> None:
    memory_path = get_memory_path(config)
    if not memory_path.exists():
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        template = load_memory_template("main").replace("{install_root}", str(config.install_root))
        memory_path.write_text(template)
        logger.init(f"Initialized main memory ({len(template)} chars)")


def init_prompts(config: vm.VestaConfig) -> None:
    prompts_dir = config.prompts_dir
    prompts_dir.mkdir(parents=True, exist_ok=True)
    for name, content in PROMPT_TEMPLATES.items():
        path = prompts_dir / f"{name}.md"
        if not path.exists():
            path.write_text(content)
            logger.init(f"Initialized prompt: {name}")


def load_prompt(name: str, config: vm.VestaConfig) -> str | None:
    path = config.prompts_dir / f"{name}.md"
    if path.exists():
        return path.read_text()
    return None


def init_skills_symlink(config: vm.VestaConfig) -> None:
    target = config.state_dir / ".claude" / "skills"
    if target.exists() and not target.is_symlink():
        raise RuntimeError(f"{target} exists and is not a symlink")
    if target.is_symlink():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(config.skills_dir)
