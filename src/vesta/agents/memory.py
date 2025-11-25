import datetime as dt
import shutil
from pathlib import Path

from ..config import VestaSettings
from .templates import MEMORY_TEMPLATES
from ..effects import logger

AGENT_NAMES = ["browser", "email_calendar", "report_writer"]


def get_memory_dir(config: VestaSettings) -> Path:
    return config.state_dir / "memory"


def get_memory_path(config: VestaSettings, *, agent_name: str = "main") -> Path:
    memory_dir = get_memory_dir(config)
    if agent_name == "main":
        return memory_dir / "MEMORY.md"
    return memory_dir / agent_name / "MEMORY.md"


def get_memory_backup_dir(config: VestaSettings) -> Path:
    return config.state_dir / "memory_backups"


def init_all_memories(config: VestaSettings) -> None:
    """Initialize memory files from templates if they don't exist."""
    for agent_name, template in MEMORY_TEMPLATES.items():
        memory_path = get_memory_path(config, agent_name=agent_name)
        if not memory_path.exists():
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            memory_path.write_text(template)
            logger.info(f"[MEMORY] Initialized {agent_name} memory from template ({len(template)} chars)")


def load_memory(config: VestaSettings, *, agent_name: str = "main") -> str:
    """Load agent memory content (which IS the system prompt)."""
    memory_path = get_memory_path(config, agent_name=agent_name)
    if memory_path.exists():
        content = memory_path.read_text()
        logger.debug(f"[MEMORY] Loaded {agent_name} memory ({len(content)} chars)")
        return content
    # Return template if file doesn't exist yet
    logger.debug(f"[MEMORY] Using template for {agent_name} (file not found)")
    return MEMORY_TEMPLATES[agent_name]


def _get_dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def backup_all_memories(config: VestaSettings) -> Path | None:
    memory_dir = get_memory_dir(config)
    if not memory_dir.exists():
        logger.debug("[MEMORY] No memory folder to backup")
        return None

    backup_base = get_memory_backup_dir(config)
    backup_base.mkdir(parents=True, exist_ok=True)

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_base / timestamp
    shutil.copytree(memory_dir, backup_path)

    size_kb = _get_dir_size(backup_path) / 1024
    logger.info(f"[MEMORY] Backup created: {backup_path.name} ({size_kb:.1f} KB)")
    return backup_path
