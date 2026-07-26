---
name: vesta-prompt-guide
description: >
  Use when writing or reviewing anything the Vesta agent itself reads: a SKILL.md body, the setup and
  reference docs it points at, comments and docstrings in a skill's own CLI code, agent/core/prompts/**,
  agent/MEMORY.md, or the agent's system prompt. TRIGGER when the user says "skill", "prompt", "system
  prompt", "agent instructions", "agent behavior", or "prompt engineering" about what the agent reads.
---

# Vesta Prompt Engineering Guide

This guide covers everything the agent reads: `agent/core/prompts/**`, `agent/MEMORY.md`, the
system prompt, and all of `agent/skills/**`. A skill is not just its `SKILL.md`; the agent reads
and edits the CLI code under it, so comments and docstrings in that code are in scope too.

Out of scope: the engine (`agent/core/*.py`), `vestad/`, and repo docs such as CLAUDE.md. Those
are read by developers rather than the agent, and the rules differ.

Before making any changes to that text, you MUST first fetch and review the official Claude Code
prompting guides to ensure best practices are followed.

## Required Reading Before Any Prompt Change

Use the WebFetch tool to retrieve the following pages and review them for relevant guidance:

1. **Claude Code Best Practices**: `https://code.claude.com/docs/en/best-practices`
2. **Claude 4 Prompting Best Practices**: `https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/claude-4-best-practices`
3. **General Prompting Overview**: `https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview`
4. **System Prompts for Claude Code SDK**: `https://docs.anthropic.com/en/docs/claude-code/sdk/modifying-system-prompts`

Fetch at minimum guides #1 and #2 before proceeding. Fetch #3 and #4 if the task involves
SDK-level system prompts or deeper prompt engineering.

## Workflow

1. **Fetch the guides** listed above using WebFetch
2. **Identify relevant best practices** from the guides that apply to the current task
3. **Review the existing prompt or skill** that needs to change
4. **Apply changes** following the official best practices
5. **Explain** which best practices informed your changes and why

## Key Principles to Watch For

- Clear, explicit instructions over vague guidance
- Concrete examples of the command or shape being described, over prose about it
- No conflicting or redundant instructions, including against what the agent already reads elsewhere
- A `description` that states when to use the skill, never a summary of its steps: an agent that can
  read the workflow from the description will follow that instead of opening the body
- Changes tested against what the agent actually does, not just how the text reads

## Never describe a previous design

The agent reads every instruction cold, with no knowledge that the system was ever different,
and cannot tell a description of the old design apart from a description of the one it is
running in. Write the mechanism, the constraint, and why it must be that way. Never what
changed, what this replaces, or what it used to do.

The test is whether the agent can **encounter** the thing, not whether the thing is in the past:

| Prose | Verdict |
| --- | --- |
| "an account authed before the client id changed must re-auth once" | Keep. A stale account is sitting there waiting to be found, and the agent has to act on it. |
| "it folds what used to be six separate files" | Delete. Changelog. |
| "vestad no longer binds only loopback" | Delete. Describe what it binds. |

That test is what keeps migration and convergence instructions writable: they describe a before
and after because the agent may find either state on disk.
