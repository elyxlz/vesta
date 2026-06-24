"""Default-skill reconciler.

The list of default skills lives in `core/default-skills.txt`, inside the
read-only core mount, so it updates deterministically with the core code on
upgrade (not deferred behind the agent's next upstream-sync, which only touches
`skills/`). Fresh vestas ship every default skill baked into the image; the
Dockerfile prunes `skills/` down to this list. Existing boxes only gain a newly
added default skill when something installs it. Rather than hand-write an install
migration per skill, this reconciler derives the work from disk on every boot:
read the list, find the defaults whose `SKILL.md` is missing under `skills/`, and
drop one notification asking the agent to install them and restart.

Self-healing and stateless: nothing is marked applied. Once a skill is installed
the next boot sees its `SKILL.md` and drops nothing, so re-running is always safe.
The notification uses a stable filename, so an un-acted-on prompt is overwritten
rather than piling up across boots.
"""

from . import logger
from . import models as vm
from .loops import drop_core_notification


def _default_skill_names(config: vm.VestaConfig) -> list[str]:
    default_skills_file = config.agent_dir / "core" / "default-skills.txt"
    if not default_skills_file.exists():
        return []
    return [line.strip() for line in default_skills_file.read_text().splitlines() if line.strip()]


def missing_default_skills(config: vm.VestaConfig) -> list[str]:
    """Default skills whose directory is not installed (no `SKILL.md` on disk)."""
    skills_dir = config.agent_dir / "skills"
    return [name for name in _default_skill_names(config) if not (skills_dir / name / "SKILL.md").exists()]


def reconcile_default_skills(*, config: vm.VestaConfig, first_start: bool = False) -> int:
    """Drop a single notification listing default skills that are missing, so the agent installs
    them. Returns the count missing. First start is a no-op: a fresh image already ships them all."""
    if first_start:
        return 0
    missing = missing_default_skills(config)
    if not missing:
        return 0
    install_lines = "\n".join(f"- {name}: `~/agent/skills/skills-registry/scripts/skills-install {name}`" for name in missing)
    body = (
        "[Default skill sync]\n\n"
        "These skills ship with every Vesta by default but are not installed on this box yet. "
        "Install each one, then restart so they load:\n\n"
        f"{install_lines}\n\n"
        "After installing all of them, call the `restart_vesta` tool. "
        "If an install fails, tell the user which one and why."
    )
    drop_core_notification(
        type_=vm.TYPE_DEFAULT_SKILL_SYNC,
        body=body,
        interrupt=False,
        config=config,
        name=vm.TYPE_DEFAULT_SKILL_SYNC,
    )
    logger.startup(f"Dropped default-skill-sync notification for {len(missing)} missing skill(s): {', '.join(missing)}")
    return len(missing)
