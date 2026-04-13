---
name: vesta-prompt-guide
description: >
  Use when the user mentions changing, updating, writing, or reviewing Vesta's prompts, system prompts,
  CLAUDE.md files, skills, skill definitions, agent instructions, or any prompt engineering work for the
  Vesta project. TRIGGER when: user says "prompt", "system prompt", "skill", "CLAUDE.md", "instructions",
  "agent behavior", "prompt engineering", or similar in the context of Vesta configuration.
---

# Vesta Prompt Engineering Guide

Before making any changes to Vesta's prompts, system prompts, skills, CLAUDE.md files, or agent
instructions, you MUST first fetch and review the official Claude Code prompting guides to ensure
best practices are followed.

## Required Reading Before Any Prompt Change

Use the WebFetch tool to retrieve the following pages and review them for relevant guidance:

1. **Claude Code Best Practices**: `https://www.anthropic.com/engineering/claude-code-best-practices`
2. **Claude 4 Prompting Best Practices**: `https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/claude-4-best-practices`
3. **General Prompting Overview**: `https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview`
4. **System Prompts for Claude Code SDK**: `https://docs.anthropic.com/en/docs/claude-code/sdk/modifying-system-prompts`

Fetch at minimum guides #1 and #2 before proceeding. Fetch #3 and #4 if the task involves
SDK-level system prompts or deeper prompt engineering.

## Workflow

1. **Fetch the guides** listed above using WebFetch
2. **Identify relevant best practices** from the guides that apply to the current task
3. **Review the existing prompt/skill/CLAUDE.md** that needs to change
4. **Apply changes** following the official best practices
5. **Explain** which best practices informed your changes and why

## Key Principles to Watch For

- Clear, explicit instructions over vague guidance
- Structured prompts with proper XML tags and sections
- Placing long context at the top, queries at the bottom
- Using examples (multishot) where appropriate
- Avoiding conflicting or redundant instructions
- Testing prompt changes against expected behavior
