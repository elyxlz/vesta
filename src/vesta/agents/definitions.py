from dataclasses import dataclass
from typing import Literal

from claude_agent_sdk.types import AgentDefinition

from ..config import VestaSettings
from .memory import init_all_memories, load_memory
from .tool_ids import (
    PLAYWRIGHT_TOOL_IDS,
    MICROSOFT_ALL_TOOL_IDS,
    PDF_READER_TOOL_IDS,
)

ModelType = Literal["sonnet", "opus", "haiku", "inherit"]


@dataclass
class AgentConfig:
    name: str
    description: str
    tools: list[str]
    model: ModelType = "inherit"


AGENT_CONFIGS: list[AgentConfig] = [
    AgentConfig(
        name="browser",
        description="Use for web browsing, screenshots, scraping with Playwright.",
        tools=PLAYWRIGHT_TOOL_IDS,
        model="haiku",
    ),
    AgentConfig(
        name="email_calendar",
        description="Use for email and calendar operations (Microsoft Outlook).",
        tools=MICROSOFT_ALL_TOOL_IDS,
    ),
    AgentConfig(
        name="report_writer",
        description="Use for creating reports, documents, and professional materials.",
        tools=PDF_READER_TOOL_IDS,
    ),
]

# Single source of truth for agent names
AGENT_NAMES: list[str] = [c.name for c in AGENT_CONFIGS]


def build_all_agents(config: VestaSettings) -> dict[str, AgentDefinition]:
    init_all_memories(config)
    return {
        agent.name: AgentDefinition(
            description=agent.description,
            prompt=load_memory(config, agent_name=agent.name),
            tools=agent.tools,
            model=agent.model,
        )
        for agent in AGENT_CONFIGS
    }
