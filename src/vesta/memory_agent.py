import asyncio
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions
from claude_code_sdk.types import AssistantMessage, TextBlock

MEMORY_PROMPT = """You are a memory agent for Vesta. Extract ONLY truly important information from conversations.

Rules:
- Be extremely concise - only save what matters
- Skip trivial interactions and test messages
- Focus on: important facts, deadlines, mistakes/learnings, key decisions
- Write clean markdown without explanations or meta-commentary
- If there's nothing important, return empty string

Format (only include sections with content):
## Updates for [Date]

### User Information
- [Only new important facts]

### Tasks & Deadlines
- [Only specific commitments]

### Learnings
- [Mistakes and how to avoid them]
- [Useful patterns discovered]

Be ruthless about brevity. Most conversations have nothing worth saving."""

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

    prompt = f"""Current MEMORY.md content:
{existing_memory}

Recent conversation to extract from:
{conversation_text}

Extract ONLY new important information. Return empty if nothing important."""

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