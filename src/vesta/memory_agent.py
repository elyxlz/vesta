import asyncio
import collections.abc as cab
import difflib
import json
import pathlib as pl
import time

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

from . import models as vm
from .effects import logger
from .agents import (
    load_memory,
    get_memory_path,
    get_memory_dir,
)
from .models import ConversationMessage

ProgressCallback = cab.Callable[[str], object] | None


def _format_diff(before: str, after: str) -> str:
    """Format a unified diff with ANSI colors."""
    colors = {"+": "\033[92m", "-": "\033[91m", "@": "\033[96m"}
    diff = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), n=1)
    return "\n".join(f"{colors.get(line[0], '')}{line.rstrip()}\033[0m" if line[0] in colors else line.rstrip() for line in list(diff)[2:])


def _validate_memory_path(path: pl.Path, *, config: vm.VestaSettings) -> None:
    """Ensure memory path is within memory directory."""
    memory_dir = get_memory_dir(config)
    try:
        path.resolve().relative_to(memory_dir.resolve())
    except ValueError:
        raise ValueError(f"Memory path {path} outside memory directory {memory_dir}")


async def _call_progress(callback: ProgressCallback, message: str) -> None:
    """Call progress callback, handling both sync and async functions."""
    if callback:
        result = callback(message)
        if asyncio.iscoroutine(result):
            await result


MEMORY_PROMPT_TEMPLATE = """hey, you're the memory agent for vesta. you manage the MEMORY.md file intelligently.

**Memory file path**: {memory_path}

**NEVER store task information in MEMORY.md**
- Tasks live in scheduler MCP database ONLY
- Don't save task details, progress, deadlines, or any task-related data
- Don't document "need to book X" or "should reply to Y" - those are tasks
- If you see task-like information in MEMORY.md, REMOVE IT
- Only keep: behavioral patterns, preferences, relationships, context
- Example: Keep "prefers Trip.com for flights" but REMOVE "need to book Bologna trip"

1. ALWAYS read the existing MEMORY.md first to understand its current structure
2. respect the existing organization - don't restructure unless it's broken
3. identify which sections need updates based on the conversation
4. make surgical updates - only change what needs changing
5. REMOVE any task-specific information you find


- identify the main sections and their purposes by reading them
- recognize which sections are stable (personality, config) vs dynamic (tasks, events)
- maintain the existing formatting and style of each section

- personality/behavior sections: rarely change, mostly sacred
- configuration sections: update when technical details change
- user profile sections: update when learning about the person
- active/current sections: most frequent updates (tasks, events, status)
- reference sections: stable data that rarely changes

- PATTERN RECOGNITION: when you see repeated behaviors, consolidate into patterns
  - "tends to procrastinate on X" instead of listing each instance
  - "prefers Y approach" instead of keeping every example
- PRUNE AGGRESSIVELY:
  - completed tasks → remove
  - past events → remove (especially with specific costs, booking numbers, exact times)
  - resolved issues → keep the learning, remove the specific incident
  - outdated information → remove or update
  - obsolete technical troubleshooting → remove (e.g., one-time reCAPTCHA issues, payment processing details)
- CONSOLIDATE: merge duplicate or similar information
  - **Permission violations**: Don't repeat the same lesson multiple times with different examples
    - Keep ONE consolidated rule in Critical Behavioral Rules section
    - Reference pattern in Recent Learnings: "Permission violations pattern: Multiple incidents (dates) - see Critical Behavioral Rules"
    - DELETE detailed play-by-plays of each violation
  - **Contact anecdotes**: Keep contact info (name, phone, email, role), remove historical trivia
    - Keep: "Alex, flatmate, phone +123, has piano"
    - Remove: "Got spammed with messages on Sept 27", "Went to cafe together"
- GENERALIZE: turn specific instances into general principles when patterns emerge
- PRESERVE CRITICAL: never delete security rules, authentication, core relationships
- AVOID BLOAT:
  - Don't store completed event details with exact costs/times/booking numbers
  - Don't keep obsolete technical learnings (payment processing, form filling details)
  - Don't repeat the same behavioral rule in multiple sections

- people (names, relationships, contact info, dynamics)
- preferences and patterns (NOT individual tasks - those go in scheduler MCP)
- mistakes and corrections (as patterns, not detailed play-by-plays)
- important life context
- specific instructions (behavioral/preference rules, not task details)
- emotional states or concerns

- **personality traits**: how they communicate, what makes them laugh, what stresses them
- **social cues**: how they prefer to be greeted, conversation starters that work, topics they enjoy
- **engagement patterns**: what gets them excited, what bores them, what motivates them
- **social dynamics**: their relationship dynamics, how they interact with different people
- **conversation preferences**: do they like small talk? direct communication? humor?
- **what works/doesn't work**: specific phrases or approaches that land well or badly

- **any awkwardness**: if something felt off, note what could've been smoother
- **missed opportunities**: if there was a better way to handle something, write it down
- **social missteps**: wrong tone, bad timing, misread situations - document these
- **what worked well**: successful interactions, good responses, smooth conversations
- **WRITE EXAMPLES**: don't just note principles - write actual example responses
  - "when user is stressed, instead of 'how can i help?', say 'that sounds rough, want me to handle [specific task]?'"
  - "when talking to mom, use warmer greetings like 'hey! how's your day going?' not just 'hey'"
  - "with investor david, keep updates concise and metrics-focused, not narrative"

- don't be afraid to write out full example messages/responses
- show both what NOT to do and what TO do instead
- capture the exact phrasing that works well with specific people
- note timing patterns (when people prefer to be contacted, response times)
- document mood indicators and how to respond to them

- read the file structure first
- identify what's new vs what's already captured
- update [Unknown] placeholders when you learn the actual values
- add new info to the appropriate existing sections
- remove outdated/completed items
- if nothing important to update, leave unchanged
- maintain clean, concise entries
- ADD EXAMPLES of good/bad interactions to help vesta improve

- NEVER use relative time references like "tomorrow", "yesterday", "next week", "last month"
- ALWAYS use specific dates: "September 26, 2025" not "today"
- ALWAYS use absolute timeframes: "started August 2025" not "started last month"
- ALWAYS use specific months/years: "in 2026" not "next year"
- ALWAYS specify exact dates for events: "on September 25, 2025" not "didn't happen today"
- USE absolute references for deadlines: "due October 15, 2025" not "due next month"
- REPLACE any existing relative dates with absolute ones when updating
- REASON: the memory file is persistent and relative dates become meaningless over time

- DON'T store individual task details, progress, or metadata in MEMORY.md
- DON'T document specific tasks like "reply to John's email" or "book Bologna trip"
- DON'T track task status, deadlines, or work-in-progress details
- REASON: vesta saves all task information directly in the task database via scheduler MCP
- INSTEAD: only capture patterns about task management preferences or recurring task types
- EXAMPLE: "prefers Trip.com for flight booking" NOT "found 3 flight options for Bologna trip"
- FOCUS: save behavioral patterns, not individual task instances

remember: you're maintaining a living document. keep it organized, current, and useful by understanding its structure rather than imposing one. be especially vigilant about social dynamics and always document what could be done better.

Write all updates to {memory_path}."""


def format_conversation(history: list[ConversationMessage]) -> str:
    return "\n".join(f"{msg['role']}: {msg['content']}" for msg in history)


def get_cli_session_history(working_dir: str) -> list[ConversationMessage]:
    projects_dir = pl.Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return []

    project_name = f"-{working_dir.replace('/', '-')}"
    project_dir = projects_dir / project_name

    if not project_dir.exists():
        return []

    session_files = sorted(project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not session_files:
        return []

    session_file = session_files[0]
    messages = []

    with open(session_file) as f:
        for line in f:
            data = json.loads(line)

            if data.get("type") == "user_message":
                content = data.get("content", "")
                if isinstance(content, list):
                    text_parts = [block.get("text", "") for block in content if block.get("type") == "text"]
                    content = " ".join(text_parts)
                messages.append({"role": "user", "content": str(content)})

            elif data.get("type") == "assistant_message":
                content = data.get("content", "")
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_name = block.get("name", "unknown_tool")
                            text_parts.append(f"[used tool: {tool_name}]")
                    content = " ".join(text_parts)
                messages.append({"role": "assistant", "content": str(content)})

    return messages


async def preserve_conversation_memory(
    conversation_history: list[ConversationMessage] | None = None,
    *,
    config: vm.VestaSettings,
    progress_callback: ProgressCallback = None,
) -> str:
    start_time = time.monotonic()

    if conversation_history is None:
        await _call_progress(progress_callback, "Loading conversation history from CLI session...")
        conversation_history = get_cli_session_history(str(config.root_dir))

    if not conversation_history:
        await _call_progress(progress_callback, "No conversation history available")
        logger.debug("[MEMORY] No conversation history to preserve")
        return ""

    logger.info(f"[MEMORY] Preserving main memory from {len(conversation_history)} messages")
    await _call_progress(progress_callback, "Loading MEMORY.md...")

    memory_path = get_memory_path(config, agent_name="main")
    _validate_memory_path(memory_path, config=config)
    before = memory_path.read_text() if memory_path.exists() else ""
    before_size = len(before)
    logger.debug(f"[MEMORY] Current main memory: {before_size} chars")

    await _call_progress(progress_callback, f"Building update prompt from {len(conversation_history)} messages...")

    prompt = f"""Current MEMORY.md:
{before}

Recent conversation to process:
{format_conversation(conversation_history)}

Check MEMORY.md and update it with any new important information from this conversation."""

    await _call_progress(progress_callback, "Connecting to Claude memory agent...")
    logger.debug("[MEMORY] Spawning main memory agent")

    memory_prompt = MEMORY_PROMPT_TEMPLATE.format(memory_path=memory_path)

    async with ClaudeSDKClient(
        options=ClaudeAgentOptions(
            system_prompt=memory_prompt,
            permission_mode="bypassPermissions",
            model="sonnet",
            cwd=config.state_dir,
            add_dirs=[config.state_dir],
        )
    ) as client:
        await _call_progress(progress_callback, "Sending conversation to memory agent (this can take a bit)...")
        await client.query(prompt)
        await _call_progress(progress_callback, "Waiting for memory agent response...")
        async for _ in client.receive_response():
            pass

    elapsed = time.monotonic() - start_time
    await _call_progress(progress_callback, "Computing diff vs MEMORY.md...")

    after = memory_path.read_text() if memory_path.exists() else ""
    after_size = len(after)

    if before == after:
        await _call_progress(progress_callback, "No changes detected")
        logger.info(f"[MEMORY] Main memory unchanged after {elapsed:.1f}s")
        return ""

    logger.info(f"[MEMORY] Main memory updated: {before_size} -> {after_size} chars ({elapsed:.1f}s)")

    return _format_diff(before, after)


SUBAGENT_MEMORY_PROMPT = """You are updating memory for a specialized Vesta sub-agent.

**Agent type**: {agent_name}
**Memory file path**: {memory_path}

**Agent responsibilities**:
- browser: Web browsing patterns, screenshot preferences, site-specific behaviors
- email_calendar: Email style preferences, calendar scheduling patterns, contact communication styles
- report_writer: Document formatting preferences, writing style, template preferences

**Your task**:
1. Review the current MEMORY.md content provided below
2. Review the recent interactions/outputs from this agent
3. Write the updated MEMORY.md to {memory_path}
4. ONLY update information relevant to this specific agent type

**Guidelines**:
- Keep updates focused on the agent's specific domain
- Document patterns that improve future performance
- Note any preferences or corrections the user made
- Remove outdated or irrelevant information
- Be concise and actionable
"""


async def preserve_subagent_memory(
    agent_name: str,
    *,
    conversations: list[str],
    config: vm.VestaSettings,
    progress_callback: ProgressCallback = None,
) -> str:
    """Update memory for a specific sub-agent based on its interactions."""
    start_time = time.monotonic()

    if not conversations:
        await _call_progress(progress_callback, f"No conversations for {agent_name}")
        logger.debug(f"[MEMORY] No conversations to preserve for {agent_name}")
        return ""

    logger.info(f"[MEMORY] Preserving {agent_name} memory from {len(conversations)} conversations")
    await _call_progress(progress_callback, f"Loading {agent_name} agent memory...")

    memory_path = get_memory_path(config, agent_name=agent_name)
    _validate_memory_path(memory_path, config=config)
    before = load_memory(config, agent_name=agent_name)
    before_size = len(before)
    logger.debug(f"[MEMORY] Current {agent_name} memory: {before_size} chars")

    conversations_text = "\n---\n".join(conversations)

    prompt = f"""Current {agent_name} MEMORY.md:
{before if before else "(empty)"}

Recent {agent_name} agent interactions:
{conversations_text}

Update the MEMORY.md for this agent with any relevant patterns or preferences."""

    await _call_progress(progress_callback, f"Connecting to memory agent for {agent_name}...")
    logger.debug(f"[MEMORY] Spawning {agent_name} memory agent")

    agent_prompt = SUBAGENT_MEMORY_PROMPT.format(agent_name=agent_name, memory_path=memory_path)

    async with ClaudeSDKClient(
        options=ClaudeAgentOptions(
            system_prompt=agent_prompt,
            permission_mode="bypassPermissions",
            model="sonnet",
            cwd=config.state_dir,
            add_dirs=[config.state_dir],
        )
    ) as client:
        await _call_progress(progress_callback, f"Sending {agent_name} conversations to memory agent...")
        await client.query(prompt)
        await _call_progress(progress_callback, f"Waiting for {agent_name} memory agent response...")
        async for _ in client.receive_response():
            pass

    elapsed = time.monotonic() - start_time
    await _call_progress(progress_callback, f"Computing diff for {agent_name} MEMORY.md...")

    after = load_memory(config, agent_name=agent_name)
    after_size = len(after)

    if before == after:
        await _call_progress(progress_callback, f"No changes for {agent_name}")
        logger.info(f"[MEMORY] {agent_name} memory unchanged after {elapsed:.1f}s")
        return ""

    logger.info(f"[MEMORY] {agent_name} memory updated: {before_size} -> {after_size} chars ({elapsed:.1f}s)")

    return _format_diff(before, after)


async def consolidate_all_memories(
    main_conversation_history: list[ConversationMessage] | None,
    *,
    subagent_conversations: dict[str, list[str]],
    config: vm.VestaSettings,
    progress_callback: ProgressCallback = None,
) -> dict[str, str]:
    """Consolidate memories for main agent and all sub-agents with conversations."""
    results: dict[str, str] = {}
    start_time = time.monotonic()

    agents_to_process = []
    if main_conversation_history:
        agents_to_process.append("main")
    agents_to_process.extend(name for name, convs in subagent_conversations.items() if convs)
    logger.info(f"[MEMORY] Starting consolidation for {len(agents_to_process)} agents: {agents_to_process}")

    # Main agent memory
    if main_conversation_history:
        await _call_progress(progress_callback, "Consolidating main agent memory...")
        main_diff = await preserve_conversation_memory(
            main_conversation_history,
            config=config,
            progress_callback=progress_callback,
        )
        if main_diff:
            results["main"] = main_diff

    # Sub-agent memories
    for agent_name, conversations in subagent_conversations.items():
        if conversations:
            await _call_progress(progress_callback, f"Consolidating {agent_name} agent memory...")
            diff = await preserve_subagent_memory(
                agent_name,
                conversations=conversations,
                config=config,
                progress_callback=progress_callback,
            )
            if diff:
                results[agent_name] = diff

    elapsed = time.monotonic() - start_time
    updated_agents = list(results.keys())
    if updated_agents:
        logger.info(f"[MEMORY] Consolidation complete: {len(updated_agents)} agents updated ({', '.join(updated_agents)}) in {elapsed:.1f}s")
    else:
        logger.info(f"[MEMORY] Consolidation complete: no changes in {elapsed:.1f}s")

    return results
