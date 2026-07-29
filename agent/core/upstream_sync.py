"""Upgrade-driven upstream sync trigger, with Git history as the source of truth."""

import os
import subprocess
import tomllib

from . import config as cfg
from . import logger

UNKNOWN_VERSION = "unknown"
# vestad bind-mounts the snapshot repo here read-only; fetch-upstream.sh reads the same path and
# honors the same VESTA_UPSTREAM_SOURCE override, so both agree on where the snapshot lives.
MOUNTED_UPSTREAM_REPO = "/run/vesta-upstream/upstream.git"


def vesta_version(config: cfg.VestaConfig) -> str:
    """Version of the code actually running, read from core/pyproject.toml (re-extracted on
    upgrade, so it tracks the running core). Best-effort: never raises over a version label."""
    pyproject = config.agent_dir / "core" / "pyproject.toml"
    if not pyproject.exists():
        return UNKNOWN_VERSION
    try:
        return tomllib.loads(pyproject.read_text())["project"]["version"]
    except (tomllib.TOMLDecodeError, KeyError, OSError) as e:
        logger.init(f"could not read version: {e}")
        return UNKNOWN_VERSION


def workspace_synced(config: cfg.VestaConfig, version: str) -> bool:
    """Whether this version's stock snapshot is already part of the workspace history."""
    workspace = str(config.agent_dir.parent)
    tag = f"agent-v{version}"
    source = os.environ["VESTA_UPSTREAM_SOURCE"] if "VESTA_UPSTREAM_SOURCE" in os.environ else MOUNTED_UPSTREAM_REPO
    try:
        # build-upstream re-tags agent-v<version> onto each fresh snapshot, so one version can move
        # to a newer commit than the local tag records. `git fetch` won't advance an existing tag
        # without --force, so refresh it from the snapshot repo before asking whether it is in
        # history: a stale tag reads as merged and the sync turn never fires. Best-effort, a missing
        # source leaves the local tag and the ancestry check falls back to it.
        subprocess.run(
            ["git", "-C", workspace, "fetch", "--force", source, f"+refs/tags/{tag}:refs/tags/{tag}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        result = subprocess.run(
            ["git", "-C", workspace, "merge-base", "--is-ancestor", tag, "HEAD"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError as e:
        logger.init(f"could not inspect workspace git history: {e}")
        return False
    return result.returncode == 0


def upstream_sync_turn(*, config: cfg.VestaConfig, first_start: bool) -> str | None:
    """Tell the agent to merge this version's snapshot when Git says it has not landed."""
    running = vesta_version(config)
    # Birth owns the initial attach. If it was interrupted, the next ordinary boot sees
    # the missing tag in history and queues this turn, so no persisted claim is needed.
    if running == UNKNOWN_VERSION or first_start:
        return None
    if workspace_synced(config, running):
        return None
    logger.startup(f"Queued upstream-sync boot turn: workspace is missing agent-v{running}")
    return (
        "[Upstream sync]\n\n"
        f"Vesta was upgraded (now v{running}). Read `~/agent/core/skills/upstream-sync/SKILL.md` "
        f"and follow it to sync your workspace to this version: fetch, checkpoint dirty work, "
        f"and run `git merge --no-ff --no-edit agent-v{running}`. Resolve any conflicts by hand. "
        "If the merge brought changes, call `restart_vesta` afterward so the new skills load; "
        "if it was a no-op, no restart is needed. If it fails, tell the user what blocked it."
    )
