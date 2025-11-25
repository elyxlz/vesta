"""AgentDefinition factory functions for Vesta sub-agents."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from claude_agent_sdk.types import AgentDefinition

from .memory import init_agent_memories, load_agent_memory
from .tool_ids import (
    PLAYWRIGHT_TOOL_IDS,
    MICROSOFT_ALL_TOOL_IDS,
    PDF_READER_TOOL_IDS,
)

if TYPE_CHECKING:
    from ..models import VestaSettings

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(filename: str) -> str:
    """Load a prompt file from the prompts directory."""
    prompt_path = PROMPTS_DIR / filename
    if prompt_path.exists():
        return prompt_path.read_text().strip()
    return ""


def build_agent_prompt(config: VestaSettings, agent_name: str) -> str:
    """Combine base prompt with agent's MEMORY.md content."""
    base_prompt = load_prompt(f"{agent_name}.txt")
    memory = load_agent_memory(config, agent_name)

    if memory:
        return f"{base_prompt}\n\n---\n\n{memory}"
    return base_prompt


def build_all_agents(config: VestaSettings) -> dict[str, AgentDefinition]:
    """Build all sub-agent definitions with their prompts and tools."""
    # Initialize memories on first run (copy templates if needed)
    init_agent_memories(config)

    return {
        "browser": AgentDefinition(
            description="Use for web browsing, screenshots, scraping with Playwright.",
            prompt=build_agent_prompt(config, "browser"),
            tools=PLAYWRIGHT_TOOL_IDS,
            model="haiku",
        ),
        "email-calendar": AgentDefinition(
            description="Use for email and calendar operations (Microsoft Outlook).",
            prompt=build_agent_prompt(config, "email_calendar"),
            tools=MICROSOFT_ALL_TOOL_IDS,
        ),
        "report-writer": AgentDefinition(
            description="Use for creating reports, documents, and professional materials.",
            prompt=build_agent_prompt(config, "report_writer"),
            tools=PDF_READER_TOOL_IDS,
        ),
    }
