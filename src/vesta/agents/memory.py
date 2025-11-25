"""Sub-agent memory initialization and loading."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import VestaSettings

AGENT_NAMES = ["browser", "email_calendar", "report_writer"]
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def get_agents_dir(config: VestaSettings) -> Path:
    """Get the base directory for all agent memories."""
    return config.state_dir / "agents"


def get_agent_memory_path(config: VestaSettings, agent_name: str) -> Path:
    """Get path to an agent's MEMORY.md file."""
    return get_agents_dir(config) / agent_name / "MEMORY.md"


def get_agent_memory_backup_dir(config: VestaSettings, agent_name: str) -> Path:
    """Get the backup directory for an agent's memory."""
    return get_agents_dir(config) / agent_name / "backups"


def init_agent_memories(config: VestaSettings) -> None:
    """Initialize agent memories from templates if they don't exist."""
    for agent_name in AGENT_NAMES:
        memory_path = get_agent_memory_path(config, agent_name)
        template_path = TEMPLATES_DIR / f"{agent_name}_MEMORY.md.tmp"

        if not memory_path.exists() and template_path.exists():
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(template_path, memory_path)


def load_agent_memory(config: VestaSettings, agent_name: str) -> str:
    """Load an agent's MEMORY.md content."""
    memory_path = get_agent_memory_path(config, agent_name)
    if memory_path.exists():
        return memory_path.read_text()
    return ""


def save_agent_memory(config: VestaSettings, agent_name: str, content: str) -> None:
    """Save content to an agent's MEMORY.md file."""
    memory_path = get_agent_memory_path(config, agent_name)
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(content)


def backup_agent_memory(config: VestaSettings, agent_name: str) -> Path | None:
    """Create a timestamped backup of an agent's MEMORY.md."""
    import datetime as dt

    memory_path = get_agent_memory_path(config, agent_name)
    if not memory_path.exists():
        return None

    backup_dir = get_agent_memory_backup_dir(config, agent_name)
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"MEMORY_{timestamp}.md"
    shutil.copy(memory_path, backup_path)
    return backup_path
