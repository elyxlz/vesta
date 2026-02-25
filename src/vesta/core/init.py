import os
import pathlib as pl

import vesta.models as vm
from vesta import logger
from vesta.templates.main import MEMORY_TEMPLATE as MAIN_MEMORY_TEMPLATE
from vesta.templates.skills import browser, calendar, email, onedrive, reminders, report_writer, tasks, what_day, whatsapp

type SkillTemplate = dict[str, str | dict[str, str]]


def get_memory_path(config: vm.VestaConfig) -> pl.Path:
    return config.memory_dir / "MEMORY.md"


def load_memory_template(name: str) -> str:
    if name == "main":
        return MAIN_MEMORY_TEMPLATE
    raise ValueError(f"Unknown memory template: {name}")


def get_skill_templates() -> dict[str, SkillTemplate]:
    return {
        "email": {"skill_md": email.SKILL_MD, "scripts": email.SCRIPTS},
        "calendar": {"skill_md": calendar.SKILL_MD, "scripts": calendar.SCRIPTS},
        "browser": {"skill_md": browser.SKILL_MD, "scripts": browser.SCRIPTS},
        "report-writer": {"skill_md": report_writer.SKILL_MD, "scripts": report_writer.SCRIPTS},
        "what-day": {"skill_md": what_day.SKILL_MD, "scripts": what_day.SCRIPTS},
        "whatsapp": {"skill_md": whatsapp.SKILL_MD, "scripts": whatsapp.SCRIPTS},
        "reminders": {"skill_md": reminders.SKILL_MD, "scripts": reminders.SCRIPTS},
        "tasks": {"skill_md": tasks.SKILL_MD, "scripts": tasks.SCRIPTS},
        "onedrive": {"skill_md": onedrive.SKILL_MD, "scripts": onedrive.SCRIPTS},
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


def init_main_memory(config: vm.VestaConfig) -> None:
    memory_path = get_memory_path(config)
    if not memory_path.exists():
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        template = load_memory_template("main")
        memory_path.write_text(template)
        logger.init(f"Initialized main memory ({len(template)} chars)")


def init_skills_symlink(config: vm.VestaConfig) -> None:
    target = config.state_dir / ".claude" / "skills"
    if target.exists() and not target.is_symlink():
        raise RuntimeError(f"{target} exists and is not a symlink")
    if target.is_symlink():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(config.skills_dir)


def check_state_readable(config: vm.VestaConfig) -> None:
    for f in config.state_dir.iterdir():
        if not os.access(f, os.R_OK):
            raise RuntimeError(f"Not readable: {f}")
