import asyncio
from pathlib import Path
from typing import List, Dict, Any

from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions
from claude_code_sdk.types import McpStdioServerConfig

MEMORY_PROMPT = """You are a memory agent for Vesta. You manage the MEMORY.md file.

Your job:
1. Read the existing MEMORY.md file (if it exists)
2. Extract important NEW information from conversations
3. Update MEMORY.md with ONLY new information (no duplicates)

Rules:
- Be extremely concise
- Skip trivial interactions
- Focus on: important facts, deadlines, mistakes/learnings, preferences
- Never duplicate existing information
- If nothing new to save, don't update the file

Use the Read tool to check existing memory, then Write tool to update if needed."""

MEMORY_FILE = Path(__file__).parent.parent.parent / "MEMORY.md"

def format_conversation(history: List[Dict[str, Any]]) -> str:
    """Convert conversation history to formatted text."""
    return "\n".join(
        f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
        for msg in history
    )

async def preserve_conversation_memory(conversation_history: List[Dict[str, Any]]) -> None:
    """Extract and save important information from conversation."""
    if not conversation_history:
        return

    conversation_text = format_conversation(conversation_history)

    # Read system prompt for context
    system_prompt_path = Path(__file__).parent.parent.parent / "SYSTEM_PROMPT.md"
    system_prompt = system_prompt_path.read_text() if system_prompt_path.exists() else ""

    prompt = f"""System context (first 2000 chars):
{system_prompt[:2000]}...

Recent conversation to process:
{conversation_text}

Check MEMORY.md and update it with any new important information from this conversation."""

    # Create client with file permissions
    options = ClaudeCodeOptions(
        system_prompt=MEMORY_PROMPT,
        mcp_servers={},
        permission_mode="bypassPermissions"  # Allow file operations without prompts
    )

    client = ClaudeSDKClient(options=options)

    try:
        await client.__aenter__()
        await client.query(prompt)

        # Let the agent handle the response
        async for _ in client.receive_response():
            pass  # Agent will use Read/Write tools directly

    except Exception as e:
        print(f"⚠️ Memory preservation failed: {e}")
    finally:
        await client.__aexit__(None, None, None)