import pathlib as pl
import subprocess

from . import logger
from . import models as vm

# Below this size, MEMORY.md is treated as wiped or partial and restored from HEAD.
# A sane MEMORY.md always has at least the Charter section and a few rules; the 20k
# upper cap is enforced by the dream skill, so anything under a few hundred bytes
# is suspicious. 200 is generous enough that legitimate small edits aren't disturbed.
MEMORY_RECOVERY_MIN_BYTES = 200


def get_memory_path(config: vm.VestaConfig) -> pl.Path:
    return config.agent_dir / "MEMORY.md"


def restore_memory_from_head_if_wiped(config: vm.VestaConfig) -> None:
    """If MEMORY.md is missing or below MEMORY_RECOVERY_MIN_BYTES, restore from `HEAD:agent/MEMORY.md`.

    Defends against the dreamer crashing mid-rewrite (OOM, SIGTERM, /compact triggered before
    the curation save) and leaving MEMORY.md empty or partially overwritten. The recovered
    version is whatever git committed last, typically the upstream-sync checkpoint or the
    end-of-dream commit. No-op (and no git invocation) when the on-disk file looks healthy.
    """
    memory_path = get_memory_path(config)
    if memory_path.exists() and memory_path.stat().st_size >= MEMORY_RECOVERY_MIN_BYTES:
        return
    repo_root = config.agent_dir.parent
    git_ref = f"HEAD:{config.agent_dir.name}/MEMORY.md"
    result = subprocess.run(
        ["git", "-C", str(repo_root), "show", git_ref],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        existing = f"{memory_path.stat().st_size}B" if memory_path.exists() else "missing"
        logger.error(f"MEMORY.md ({existing}) below threshold and HEAD restore failed: {result.stderr.strip()}")
        return
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(result.stdout)
    logger.startup(f"Restored MEMORY.md from HEAD ({len(result.stdout)} bytes); previous on-disk state was missing or wiped")


def load_prompt(name: str, config: vm.VestaConfig) -> str | None:
    agent_path = config.prompts_dir / f"{name}.md"
    if agent_path.exists():
        return agent_path.read_text()
    core_path = config.core_prompts_dir / f"{name}.md"
    if core_path.exists():
        return core_path.read_text()
    return None


def build_restart_context(reason: str, config: vm.VestaConfig, *, extras: list[str] | None = None) -> str:
    parts = [f"[System: {reason}]"]
    if extras:
        parts.extend(extras)
    greeting = load_prompt("restart", config) or ""
    if greeting.strip():
        parts.append(greeting.strip())
    return "\n\n".join(parts)
