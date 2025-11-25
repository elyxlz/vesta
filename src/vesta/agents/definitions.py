"""AgentDefinition factory functions for Vesta sub-agents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from claude_agent_sdk.types import AgentDefinition

from .memory import init_all_memories, load_memory
from .tool_ids import (
    PLAYWRIGHT_TOOL_IDS,
    MICROSOFT_ALL_TOOL_IDS,
    PDF_READER_TOOL_IDS,
)

if TYPE_CHECKING:
    from ..models import VestaSettings


def build_all_agents(config: VestaSettings) -> dict[str, AgentDefinition]:
    """Build all sub-agent definitions with their prompts and tools."""
    # Initialize memories on first run (copy templates if needed)
    init_all_memories(config)

    return {
        "browser": AgentDefinition(
            description="Use for web browsing, screenshots, scraping with Playwright.",
            prompt=load_memory(config, "browser"),
            tools=PLAYWRIGHT_TOOL_IDS,
            model="haiku",
        ),
        "email_calendar": AgentDefinition(
            description="Use for email and calendar operations (Microsoft Outlook).",
            prompt=load_memory(config, "email_calendar"),
            tools=MICROSOFT_ALL_TOOL_IDS,
        ),
        "report_writer": AgentDefinition(
            description="Use for creating reports, documents, and professional materials.",
            prompt=load_memory(config, "report_writer"),
            tools=PDF_READER_TOOL_IDS,
        ),
    }
