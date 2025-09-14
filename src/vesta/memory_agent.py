import asyncio
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions
from claude_code_sdk.types import AssistantMessage, TextBlock

MEMORY_PROMPT = """You are a memory agent for Vesta, a personal AI assistant. Extract ONLY truly important information from conversations.

Context: You'll receive Vesta's system prompt (which contains user info, preferences, and rules) and existing memory. Only save NEW information not already documented.

Rules:
- Be extremely concise - only save what matters
- Skip trivial interactions, test messages, and casual chat
- Focus on: personal facts, commitments, deadlines, mistakes/learnings, preferences
- Write clean markdown without explanations or thinking
- Return empty string if nothing important to add

Format (only include sections with content):
## Updates for [Date]

### User Information
- [New facts about user not in system prompt]

### Tasks & Commitments
- [Specific deadlines or promises made]

### Learnings
- [Mistakes and fixes]
- [New patterns discovered]

Be ruthless. Most conversations have nothing worth saving."""

MEMORY_FILE = Path(__file__).parent.parent.parent / "MEMORY.md"

def format_conversation(history: List[Dict[str, Any]]) -> str:
    """Convert conversation history to formatted text."""
    return "\n".join(
        f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
        for msg in history
    )

def read_existing_memory() -> str:
    """Read existing memory file if it exists."""
    return MEMORY_FILE.read_text() if MEMORY_FILE.exists() else ""

def write_memory_update(new_content: str) -> None:
    """Append new memory content to file."""
    if not new_content.strip():
        return

    # Skip if it's just the agent's thinking or meta-commentary
    skip_phrases = ["I'll extract", "I need permission", "Would you like me", "Here's what I've extracted"]
    if any(phrase in new_content for phrase in skip_phrases):
        return

    existing = read_existing_memory()

    if not existing.strip():
        updated = f"# Vesta Memory Log\n\n{new_content}"
    else:
        updated = f"{existing}\n\n{new_content}"

    MEMORY_FILE.write_text(updated)
    print(f"✅ Memory preserved to {MEMORY_FILE}")

async def create_memory_client() -> ClaudeSDKClient:
    """Create a new Claude client for memory processing."""
    options = ClaudeCodeOptions(
        system_prompt=MEMORY_PROMPT
    )
    client = ClaudeSDKClient(options=options)
    await client.__aenter__()
    return client

async def extract_memory(client: ClaudeSDKClient, conversation_history: List[Dict[str, Any]]) -> Optional[str]:
    """Extract important information from conversation using Claude."""
    existing_memory = read_existing_memory()
    conversation_text = format_conversation(conversation_history)

    # Read Vesta's system prompt for context
    system_prompt_path = Path(__file__).parent.parent.parent / "SYSTEM_PROMPT.md"
    system_prompt = system_prompt_path.read_text() if system_prompt_path.exists() else ""

    prompt = f"""Vesta's System Prompt (for context about what matters):
{system_prompt[:2000]}...

Current MEMORY.md content:
{existing_memory}

Recent conversation to extract from:
{conversation_text}

Extract ONLY new important information that isn't already in memory or system prompt. Return empty if nothing important."""

    await client.query(prompt)

    responses = []
    async for msg in client.receive_response():
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    responses.append(block.text)

    return "\n".join(responses) if responses else None

async def preserve_conversation_memory(conversation_history: List[Dict[str, Any]]) -> None:
    """Main function to preserve memory from a conversation."""
    if not conversation_history:
        return

    client = None
    try:
        client = await create_memory_client()
        new_memory = await extract_memory(client, conversation_history)

        if new_memory:
            write_memory_update(new_memory)
    except Exception as e:
        print(f"⚠️ Memory preservation failed: {e}")
    finally:
        if client:
            await client.__aexit__(None, None, None)