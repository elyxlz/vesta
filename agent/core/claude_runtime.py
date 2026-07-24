"""Prepare Claude Code's user-scoped runtime files before the first SDK session."""

import pathlib as pl
import shutil
import subprocess

from . import config as cfg


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


def reconcile_claude_runtime(config: cfg.VestaConfig) -> None:
    """Seed active skills, rebuild their symlinks, and ensure Claude has default settings."""
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

    settings = claude_dir / "settings.json"
    if not settings.exists():
        settings.write_text('{"permissions":{"allow":[]}}\n')
