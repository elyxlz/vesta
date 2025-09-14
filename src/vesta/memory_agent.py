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
    print(f"📝 Memory agent: Starting preservation...")

    if not conversation_history:
        print(f"📝 Memory agent: No conversation history to preserve")
        return

    conversation_text = format_conversation(conversation_history)
    print(f"📝 Memory agent: Processing {len(conversation_history)} messages")

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
        print(f"📝 Memory agent: Initializing Claude client...")
        await client.__aenter__()

        print(f"📝 Memory agent: Sending query to agent...")
        await client.query(prompt)

        # Let the agent handle the response with timeout
        print(f"📝 Memory agent: Waiting for agent response...")
        response_count = 0
        try:
            async for msg in client.receive_response():
                response_count += 1
                print(f"📝 Memory agent: Received response {response_count}")
        except asyncio.TimeoutError:
            print(f"⚠️ Memory agent timeout after {response_count} responses")

        print(f"✅ Memory preservation complete")
    except Exception as e:
        import traceback
        print(f"⚠️ Memory preservation failed: {e}")
        print(f"📝 Traceback: {traceback.format_exc()}")
    finally:
        print(f"📝 Memory agent: Cleaning up...")
        await client.__aexit__(None, None, None)