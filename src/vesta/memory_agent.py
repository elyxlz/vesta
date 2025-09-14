import asyncio
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions
from claude_code_sdk.types import AssistantMessage, TextBlock

MEMORY_PROMPT = """You are a memory preservation and learning agent for Vesta. Your job is to extract important information AND learn from mistakes to improve future performance.

When given a conversation history, extract:

1. **New Facts & Information**
   - Facts about the user
   - Important events
   - Tasks and decisions
   - Preferences and patterns
   - Relationship updates
   - Dates and deadlines

2. **Learning & Improvements**
   - Mistakes made and how to avoid them
   - Inefficient approaches and better alternatives
   - Successful solutions to remember
   - Patterns that worked well
   - Command shortcuts discovered
   - Tool usage optimizations

3. **Performance Notes**
   - Tasks that took too long and why
   - Commands that failed and correct versions
   - Workarounds discovered
   - Successful strategies

Format as clean markdown for MEMORY.md:

## Updates for [Current Date]

### User Information
- [New personal details]

### Events & Activities
- [Important events]

### Tasks & Decisions
- [Completed/pending tasks]

### Learning & Improvements
- **Mistake**: [What went wrong]
  **Solution**: [How to do it right next time]
- **Optimization**: [Slow approach] → [Faster approach]
- **Pattern**: [Successful pattern to remember]

### Tool & Command Notes
- [Specific commands that work]
- [Tool combinations that are effective]
- [Shortcuts discovered]

### Performance Optimizations
- [Ways to be faster next time]

Omit empty sections. Focus on actionable learnings."""

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

Extract and format ONLY the new, important information from this conversation."""

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