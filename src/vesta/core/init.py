"""Startup initialization and template loading."""

import pathlib as pl

import vesta.models as vm
from vesta import logger
from vesta.templates.main import MEMORY_TEMPLATE as MAIN_MEMORY_TEMPLATE
from vesta.templates.skills import browser, calendar, email, report_writer, what_day

type SkillTemplate = dict[str, str | dict[str, str]]


def get_memory_dir(config: vm.VestaConfig) -> pl.Path:
    return config.state_dir / "memory"


def get_memory_path(config: vm.VestaConfig) -> pl.Path:
    return get_memory_dir(config) / "MEMORY.md"


def get_backups_dir(config: vm.VestaConfig) -> pl.Path:
    return config.backups_dir


def get_skills_dir(config: vm.VestaConfig) -> pl.Path:
    return get_memory_dir(config) / "skills"


def get_dreamer_prompt_path(config: vm.VestaConfig) -> pl.Path:
    return get_memory_dir(config) / "DREAMER_PROMPT.md"


def load_memory_template(name: str) -> str:
    if name == "main":
        return MAIN_MEMORY_TEMPLATE
    raise ValueError(f"Unknown memory template: {name}")


def get_skill_templates() -> dict[str, SkillTemplate]:
    return {
        "email": {"skill_md": email.SKILL_MD, "scripts": getattr(email, "SCRIPTS", {})},
        "calendar": {"skill_md": calendar.SKILL_MD, "scripts": getattr(calendar, "SCRIPTS", {})},
        "browser": {"skill_md": browser.SKILL_MD, "scripts": getattr(browser, "SCRIPTS", {})},
        "report-writer": {"skill_md": report_writer.SKILL_MD, "scripts": getattr(report_writer, "SCRIPTS", {})},
        "what-day": {"skill_md": what_day.SKILL_MD, "scripts": getattr(what_day, "SCRIPTS", {})},
    }


def init_skills(config: vm.VestaConfig) -> None:
    """Initialize skills from templates if they don't exist."""
    skills_dir = get_skills_dir(config)
    skill_templates = get_skill_templates()

    for skill_name, skill_data in skill_templates.items():
        skill_dir = skills_dir / skill_name
        skill_md_path = skill_dir / "SKILL.md"

        if skill_md_path.exists():
            continue

        skill_dir.mkdir(parents=True, exist_ok=True)

        # Write SKILL.md
        skill_md_content = skill_data.get("skill_md", "")
        if isinstance(skill_md_content, str):
            skill_md_path.write_text(skill_md_content)

        # Write scripts if present
        scripts = skill_data.get("scripts", {})
        if isinstance(scripts, dict) and scripts:
            scripts_dir = skill_dir / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            for script_name, script_content in scripts.items():
                script_path = scripts_dir / script_name
                script_path.write_text(script_content)
                script_path.chmod(0o755)

        logger.info(f"[INIT] Initialized skill: {skill_name}")


def init_main_memory(config: vm.VestaConfig) -> None:
    """Initialize main memory from template if it doesn't exist."""
    memory_path = get_memory_path(config)
    if not memory_path.exists():
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        template = load_memory_template("main")
        memory_path.write_text(template)
        logger.info(f"[INIT] Initialized main memory ({len(template)} chars)")


def init_dreamer_prompt(config: vm.VestaConfig) -> None:
    """Initialize dreamer prompt from template if it doesn't exist."""
    from vesta.templates.dreamer import PROMPT_TEMPLATE

    prompt_path = get_dreamer_prompt_path(config)
    if not prompt_path.exists():
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(PROMPT_TEMPLATE)
        logger.info("[INIT] Initialized dreamer prompt")
