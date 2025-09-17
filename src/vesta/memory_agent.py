from pathlib import Path
from typing import List, Dict, Any

from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions

MEMORY_PROMPT = """hey, you're the memory agent for vesta. you manage the MEMORY.md file.

your thing:
1. check the existing MEMORY.md (if it exists)
2. pick out actually important NEW info from conversations
3. update MEMORY.md - add new stuff OR update existing info (like changing [Unknown] to real values)

vibe check:
- keep it tight and concise
- skip the boring stuff
- what matters: actual facts, personal details, deadlines, things we messed up/learned, preferences
- if you spot [Unknown] fields and now know the answer, update them
- don't repeat stuff that's already there
- if there's nothing worth saving, just leave it alone

use Read to check what's there, then Write if you need to update."""

MEMORY_FILE = Path(__file__).parent.parent.parent / "MEMORY.md"


def format_conversation(history: List[Dict[str, Any]]) -> str:
    """Convert conversation history to formatted text."""
    return "\n".join(
        f"{msg.get('role', 'unknown')}: {msg.get('content', '')}" for msg in history
    )


async def preserve_conversation_memory(
    conversation_history: List[Dict[str, Any]],
) -> None:
    """Extract and save important information from conversation."""
    if not conversation_history:
        return

    conversation_text = format_conversation(conversation_history)

    # Read system prompt for context
    system_prompt_path = Path(__file__).parent.parent.parent / "SYSTEM_PROMPT.md"
    system_prompt = (
        system_prompt_path.read_text() if system_prompt_path.exists() else ""
    )

    prompt = f"""System context (first 2000 chars):
{system_prompt[:2000]}...

Recent conversation to process:
{conversation_text}

Check MEMORY.md and update it with any new important information from this conversation."""

    # Create client with file permissions
    options = ClaudeCodeOptions(
        system_prompt=MEMORY_PROMPT,
        mcp_servers={},
        permission_mode="bypassPermissions",  # Allow file operations without prompts
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
