from claude_agent_sdk.types import AgentDefinition

from ..config import VestaSettings
from .memory import init_all_memories, load_memory
from .tool_ids import (
    PLAYWRIGHT_TOOL_IDS,
    MICROSOFT_ALL_TOOL_IDS,
    PDF_READER_TOOL_IDS,
)


def build_all_agents(config: VestaSettings) -> dict[str, AgentDefinition]:
    # Initialize memories on first run (copy templates if needed)
    init_all_memories(config)

    return {
        "browser": AgentDefinition(
            description="Use for web browsing, screenshots, scraping with Playwright.",
            prompt=load_memory(config, agent_name="browser"),
            tools=PLAYWRIGHT_TOOL_IDS,
            model="haiku",
        ),
        "email_calendar": AgentDefinition(
            description="Use for email and calendar operations (Microsoft Outlook).",
            prompt=load_memory(config, agent_name="email_calendar"),
            tools=MICROSOFT_ALL_TOOL_IDS,
        ),
        "report_writer": AgentDefinition(
            description="Use for creating reports, documents, and professional materials.",
            prompt=load_memory(config, agent_name="report_writer"),
            tools=PDF_READER_TOOL_IDS,
        ),
    }
