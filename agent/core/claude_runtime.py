"""Prepare Claude Code's user-scoped runtime files before the first SDK session."""

import os
import pathlib as pl
import shutil
import subprocess

from . import config as cfg
from . import logger


def _text_names(path: pl.Path) -> list[str]:
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def _valid_skill_names(names: list[str]) -> list[str]:
    valid: set[str] = set()
    for name in names:
        try:
            valid.update(cfg.VestaConfig.model_validate({"active_skills": [name]}).active_skills)
        except ValueError:
            continue
    return sorted(valid)


def _bridge_legacy_sparse_skills(config: cfg.VestaConfig, legacy_active: pl.Path) -> None:
    """Preserve a cone checkout's active skills on its first flat-checkout boot."""
    # LEGACY(remove-when: the 2026-08-flat-checkout migration is fleet-applied): a cone box
    # has only its active skills on disk, so capture that cone before creating config.json.
    workspace_dir = config.agent_dir.parent
    if (config.data_dir / "config.json").exists() or legacy_active.exists() or not (workspace_dir / ".git/info/sparse-checkout").is_file():
        return

    result = subprocess.run(
        ["git", "sparse-checkout", "list"],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    names = [line.removeprefix("agent/skills/") for line in result.stdout.splitlines() if line.startswith("agent/skills/")]
    legacy_active.parent.mkdir(parents=True, exist_ok=True)
    legacy_active.write_text("".join(f"{name}\n" for name in sorted(set(names))))


def _replace_skill_links(link_dir: pl.Path, optional_dir: pl.Path, core_dir: pl.Path, active: list[str]) -> None:
    if link_dir.is_symlink() or (link_dir.exists() and not link_dir.is_dir()):
        link_dir.unlink()
    elif link_dir.exists():
        shutil.rmtree(link_dir)
    link_dir.mkdir(parents=True)

    def link_skill(skill_dir: pl.Path) -> None:
        if not (skill_dir / "SKILL.md").is_file():
            return
        link = link_dir / skill_dir.name
        link.unlink(missing_ok=True)
        link.symlink_to(skill_dir, target_is_directory=True)

    for name in active:
        link_skill(optional_dir / name)
    if core_dir.is_dir():
        for skill_dir in sorted(core_dir.iterdir()):
            if skill_dir.is_dir():
                link_skill(skill_dir)


def _vestad_commands(skills_dir: pl.Path) -> dict[str, pl.Path]:
    """Maps each vestad helper command to the script it runs.

    Every executable in the vestad skill's `scripts/` lands under its own filename, so the
    skill owns its command surface (`vestad-health` is named for PATH there: `health` alone
    is too generic to own).
    """
    scripts_dir = skills_dir / "vestad/scripts"
    sources: dict[str, pl.Path] = {}
    if scripts_dir.is_dir():
        for script in sorted(scripts_dir.iterdir()):
            if script.is_file() and "." not in script.name and os.access(script, os.X_OK):
                sources[script.name] = script
    return sources


def _link_vestad_commands(bin_dir: pl.Path, skills_dir: pl.Path) -> None:
    """Put the vestad helpers on PATH, one symlink at a time.

    These are core infrastructure the agent does not author, so startup owns their links; a
    skill's own command is linked from that skill's setup instead. The bin dir is shared with
    uv tool installs and those skill-owned links, so only our own helper links are touched: a
    path held by anything else keeps it, a link of ours is rewritten, and one whose script is
    gone is removed, so a moved, renamed, or deleted helper leaves nothing dangling behind it.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    for link in bin_dir.iterdir():
        if link.is_symlink() and skills_dir in link.readlink().parents and not link.exists():
            link.unlink()
    for command, source in _vestad_commands(skills_dir).items():
        link = bin_dir / command
        if not source.is_file():
            continue
        if link.is_symlink() and skills_dir in link.readlink().parents:
            link.unlink()
        elif link.is_symlink() or link.exists():
            logger.warning(f"leaving {link} alone: occupied by something other than a vestad command link")
            continue
        link.symlink_to(source)


def _clear_daemon_records(daemons_dir: pl.Path) -> None:
    """Empty the daemon pid/port records, whose one writer is a skill's own daemon start.

    Boot runs before any daemon does, so every record present is from a process the container
    no longer has. A pid it names can already belong to something else in the fresh pid space,
    which would read as live and turn the next start into a silent no-op. A record is a file, so
    a directory here belongs to whoever put it there and boot leaves it standing.
    """
    if not daemons_dir.is_dir():
        return
    for record in daemons_dir.iterdir():
        if not record.is_dir():
            record.unlink(missing_ok=True)


def reconcile_claude_runtime(config: cfg.VestaConfig) -> None:
    """Seed active skills, rebuild their symlinks, link the vestad helpers, clear stale daemon records, and ensure Claude's default settings.

    Startup links only the vestad helpers, which are core infrastructure; a skill links its own
    command from that skill's setup (a `cli/` project, or an `ln -sf` for a single launcher).
    """
    legacy_active = config.data_dir / "active-skills.txt"
    _bridge_legacy_sparse_skills(config, legacy_active)

    store = cfg.read_config_store()
    configured = store.get("active_skills")
    names = [name for name in configured if isinstance(name, str)] if isinstance(configured, list) else _text_names(legacy_active)
    names.extend(_text_names(config.agent_dir / "core/default-skills.txt"))
    active = _valid_skill_names(names)
    cfg.update_config_store({"active_skills": active})
    config.active_skills = active

    claude_dir = pl.Path.home() / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    _replace_skill_links(claude_dir / "skills", config.agent_dir / "skills", config.agent_dir / "core/skills", active)
    _link_vestad_commands(pl.Path.home() / ".local/bin", config.agent_dir / "skills")
    _clear_daemon_records(config.data_dir / "daemons")

    settings = claude_dir / "settings.json"
    if not settings.exists():
        settings.write_text('{"permissions":{"allow":[]}}\n')
