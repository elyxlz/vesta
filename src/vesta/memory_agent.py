from pathlib import Path
from typing import List, Dict, Any
import difflib

from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions

MEMORY_PROMPT = """hey, you're the memory agent for vesta. you manage the MEMORY.md file.

your thing:
1. check the existing MEMORY.md (if it exists)
2. pick out actually important NEW info from conversations
3. update MEMORY.md - add new stuff OR update existing info (like changing [Unknown] to real values)
4. PRUNE outdated stuff - remove completed tasks, old specific details, irrelevant info

what to capture:
- people mentioned (names, relationships, phone numbers, emails, character traits, how user feels about them)
- new tasks, deadlines, commitments, things user said they'd do
- preferences (what user likes/dislikes, what annoys them, what they want vesta to do/not do)
- mistakes vesta made & corrections (so she doesn't repeat them)
- important context about user's life (work stress, relationship updates, health stuff)
- patterns to watch for (spam senders, people to ignore, recurring issues)
- specific instructions about how to handle things
- any phone numbers, addresses, or contact info mentioned
- user's emotional state or concerns they expressed

pruning & generalizing:
- REMOVE completed tasks (like "sent email to X" after it's done)
- DELETE outdated specific details (old meeting times that passed, resolved issues)
- TRANSFORM repeated specifics into patterns (e.g. "always forgets to reply to mom" instead of listing each instance)
- GENERALIZE learnings (e.g. "prefers morning meetings" instead of keeping every meeting preference)
- CLEAN UP stale reminders that already happened
- CONSOLIDATE similar info into single entries
- if something was temporary and is over, remove it
- keep the learning but drop the specific incident once it's resolved

vibe check:
- keep it tight and concise
- if someone new is mentioned, add them to People in Your Life section
- if you learn something new about an existing person, update their entry
- capture character traits and relationship dynamics
- note who to trust, who to be careful with, who's spam
- if you spot [Unknown] fields and now know the answer, update them
- don't repeat stuff that's already there
- if there's nothing worth saving, just leave it alone
- actively remove stuff that's no longer relevant
- prefer patterns over specific instances when you see repetition

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
            model="opus",
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
