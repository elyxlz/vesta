"""Prepare Claude Code's user-scoped runtime files before the first SDK session."""

import json
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


HOOKS_DECLARATION = "hooks.json"


def _declared_hooks(skill_dir: pl.Path) -> dict[str, list[tuple[str, str]]]:
    """Read one skill's `hooks.json` as {event: [(matcher, absolute command)]}.

    The declaration names a script RELATIVE to its own skill, because a skill cannot know where it
    will be installed and a hardcoded path is the classic way a hook becomes a no-op on another
    box. A declared script that is not on disk is dropped with a warning for the same reason: a
    hook whose command does not exist fails silently and reads exactly like a guard that agreed.
    """
    declaration = skill_dir / HOOKS_DECLARATION
    if not declaration.is_file():
        return {}
    try:
        raw = json.loads(declaration.read_text())
    except (OSError, ValueError) as exc:
        logger.warning(f"ignoring {declaration}: {exc}")
        return {}
    if not isinstance(raw, dict):
        logger.warning(f"ignoring {declaration}: expected an object of event -> entries")
        return {}

    declared: dict[str, list[tuple[str, str]]] = {}
    for event, entries in raw.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            script, matcher = entry.get("script"), entry.get("matcher")
            if not isinstance(script, str) or not isinstance(matcher, str):
                continue
            target = skill_dir / script
            if not target.is_file():
                logger.warning(f"{declaration} names {script}, which is not on disk: not wiring it")
                continue
            declared.setdefault(event, []).append((matcher, f"python3 {target}"))
    return declared


def _merge_skill_hooks(settings_path: pl.Path, skill_dirs: list[pl.Path]) -> None:
    """Wire every active skill's declared hooks into settings.json, additively and idempotently.

    Before this, a skill that shipped a PreToolUse guard also shipped a paragraph telling each
    agent to hand-edit `~/.claude/settings.json`, and the writer above only creates that file when
    it is ABSENT, so on every existing box the guard stayed inert while the skill read as installed.
    That is the same silent-no-op shape the guards themselves exist to catch, one layer up.

    Merging is add-only and keyed by command, so a hand-written entry is never touched, a user who
    deliberately deletes a hook gets it back on the next boot (the declaration is the source of
    truth), and running this twice changes nothing the second time.
    """
    try:
        settings = json.loads(settings_path.read_text()) if settings_path.is_file() else {}
    except (OSError, ValueError) as exc:
        logger.warning(f"leaving {settings_path} alone: {exc}")
        return
    if not isinstance(settings, dict):
        return

    hooks = settings.get("hooks")
    hooks = hooks if isinstance(hooks, dict) else {}
    added = 0
    for skill_dir in skill_dirs:
        for event, entries in _declared_hooks(skill_dir).items():
            bucket = hooks.get(event)
            bucket = bucket if isinstance(bucket, list) else []
            wired = {
                hook.get("command")
                for group in bucket
                if isinstance(group, dict)
                for hook in (group.get("hooks") if isinstance(group.get("hooks"), list) else [])
                if isinstance(hook, dict)
            }
            for matcher, command in entries:
                if command in wired:
                    continue
                bucket.append({"matcher": matcher, "hooks": [{"type": "command", "command": command}]})
                wired.add(command)
                added += 1
            hooks[event] = bucket

    if not added:
        return
    settings["hooks"] = hooks
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    logger.client(f"wired {added} skill-declared hook(s) into {settings_path}")


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
    _merge_skill_hooks(
        settings, [config.agent_dir / "skills" / name for name in active] + [config.agent_dir / "core/skills" / name for name in active]
    )
