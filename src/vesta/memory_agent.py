from pathlib import Path
from typing import List, Dict, Any
import difflib

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
) -> str:
    if not conversation_history:
        return ""

    before = MEMORY_FILE.read_text() if MEMORY_FILE.exists() else ""

    system_prompt_path = Path(__file__).parent.parent.parent / "SYSTEM_PROMPT.md"
    system_prompt = (
        system_prompt_path.read_text() if system_prompt_path.exists() else ""
    )

    prompt = f"""System context (first 2000 chars):
{system_prompt[:2000]}...

Recent conversation to process:
{format_conversation(conversation_history)}

Check MEMORY.md and update it with any new important information from this conversation."""

    client = ClaudeSDKClient(
        ClaudeCodeOptions(
            system_prompt=MEMORY_PROMPT,
            mcp_servers={},
            model="claude-opus-4-1-20250805",  # Using latest Opus 4.1 model
            permission_mode="bypassPermissions",
        )
    )

    try:
        await client.__aenter__()
        await client.query(prompt)
        async for _ in client.receive_response():
            pass
    except Exception as e:
        print(f"⚠️ Memory preservation failed: {e}")
        return ""
    finally:
        await client.__aexit__(None, None, None)

    after = MEMORY_FILE.read_text() if MEMORY_FILE.exists() else ""
    if before == after:
        return ""

    colors = {"+": "\033[92m", "-": "\033[91m", "@": "\033[96m"}
    diff = difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True), n=1
    )

    return "\n".join(
        f"{colors.get(line[0], '')}{line.rstrip()}\033[0m"
        if line[0] in colors
        else line.rstrip()
        for line in list(diff)[2:]
    )
