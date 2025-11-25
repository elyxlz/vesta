"""Memory initialization and loading for all agents."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from .templates import MEMORY_TEMPLATES

if TYPE_CHECKING:
    from ..models import VestaSettings

AGENT_NAMES = ["browser", "email_calendar", "report_writer"]


def get_memory_dir(config: VestaSettings) -> Path:
    """Get the base directory for all memories."""
    return config.state_dir / "memory"


def get_memory_path(config: VestaSettings, agent_name: str = "main") -> Path:
    """Get path to an agent's MEMORY.md file."""
    memory_dir = get_memory_dir(config)
    if agent_name == "main":
        return memory_dir / "MEMORY.md"
    return memory_dir / agent_name / "MEMORY.md"


def get_memory_backup_dir(config: VestaSettings, agent_name: str = "main") -> Path:
    """Get the backup directory for an agent's memory."""
    memory_dir = get_memory_dir(config)
    if agent_name == "main":
        return memory_dir / "backups"
    return memory_dir / agent_name / "backups"


def init_all_memories(config: VestaSettings) -> None:
    """Initialize all memory files from templates if they don't exist."""
    for agent_name, template in MEMORY_TEMPLATES.items():
        memory_path = get_memory_path(config, agent_name)
        if not memory_path.exists():
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            memory_path.write_text(template)


def load_memory(config: VestaSettings, agent_name: str = "main") -> str:
    """Load an agent's memory content (which IS the system prompt)."""
    memory_path = get_memory_path(config, agent_name)
    if memory_path.exists():
        return memory_path.read_text()
    # Return template if file doesn't exist yet
    return MEMORY_TEMPLATES.get(agent_name, "")


def save_memory(config: VestaSettings, agent_name: str, content: str) -> None:
    """Save content to an agent's MEMORY.md file."""
    memory_path = get_memory_path(config, agent_name)
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(content)


def backup_memory(config: VestaSettings, agent_name: str = "main") -> Path | None:
    """Create a timestamped backup of an agent's MEMORY.md."""
    memory_path = get_memory_path(config, agent_name)
    if not memory_path.exists():
        return None

    backup_dir = get_memory_backup_dir(config, agent_name)
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"MEMORY_{timestamp}.md"
    shutil.copy(memory_path, backup_path)
    return backup_path
