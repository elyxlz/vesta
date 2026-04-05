#!/usr/bin/env python3
"""Compress a raw session transcript JSON into a clean text file for the dreamer.

Usage:
    compress.py <input.json> [output.txt]

If output is omitted, writes to <input>_compressed.txt.

What it keeps:
- User messages (verbatim) — tagged with source (console, whatsapp, notification, etc.)
- Assistant text responses (verbatim)
- Tool use compressed to one-liners: "Edited /path/to/file.py" or "Ran: git status"
- Group chat messages tagged with group name for context scanning

What it drops:
- Thinking blocks (internal reasoning)
- Tool results (file contents, command output, error dumps)
- System reminder boilerplate
- Empty messages
"""

import json
import re
import sys
from pathlib import Path


def _extract_text_blocks(content):
    """Extract text from content (string or list of blocks)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"].strip())
        return "\n".join(parts)
    return ""


def _compress_tool_use(block):
    """Turn a tool_use block into a one-liner."""
    name = block.get("name", "?")
    inp = block.get("input", {})

    if name == "Bash":
        cmd = inp.get("command", "")
        # Truncate long commands
        if len(cmd) > 120:
            cmd = cmd[:120] + "..."
        return f"[Ran: {cmd}]"
    elif name == "Edit":
        path = inp.get("file_path", "?")
        return f"[Edited {path}]"
    elif name == "Write":
        path = inp.get("file_path", "?")
        return f"[Wrote {path}]"
    elif name == "Read":
        path = inp.get("file_path", "?")
        return f"[Read {path}]"
    elif name == "Grep":
        pattern = inp.get("pattern", "?")
        return f"[Searched for: {pattern}]"
    elif name == "Glob":
        pattern = inp.get("pattern", "?")
        return f"[Glob: {pattern}]"
    elif name == "Agent":
        desc = inp.get("description", inp.get("prompt", "?")[:80])
        return f"[Sub-agent: {desc}]"
    elif name == "Skill":
        skill = inp.get("skill", "?")
        return f"[Skill: {skill}]"
    elif name.startswith("mcp__vesta__"):
        tool = name.replace("mcp__vesta__", "")
        return f"[Tool: {tool}]"
    else:
        return f"[Tool: {name}]"


def _detect_wa_group(text):
    """Try to detect if a user message is a WhatsApp group notification."""
    # Notifications typically contain chat_name= field
    match = re.search(r"chat_name=([^,\n]+)", text)
    if match:
        return match.group(1).strip()
    return None


def _strip_system_reminders(text):
    """Remove <system-reminder>...</system-reminder> blocks from text."""
    return re.sub(r"<system-reminder>.*?</system-reminder>\s*", "", text, flags=re.DOTALL).strip()


def _is_pure_system_reminder(text):
    """Check if text is ONLY system-reminder blocks with no real content."""
    stripped = _strip_system_reminders(text)
    return not stripped or stripped.startswith("[System:")


def compress_session(input_path, output_path=None):
    """Main compression pipeline."""
    with open(input_path) as f:
        messages = json.load(f)

    if output_path is None:
        output_path = str(input_path).replace(".json", "_compressed.txt")

    lines = []
    lines.append(f"# Session transcript — {len(messages)} raw messages")
    lines.append(f"# Compressed by compress.py")
    lines.append("")

    msg_count = 0
    dropped_thinking = 0
    dropped_tool_results = 0
    dropped_system = 0

    for m in messages:
        msg = m.get("message", {})
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", "?")
        content = msg.get("content", "")

        if isinstance(content, str):
            text = content.strip()
            if not text:
                continue

            if _is_pure_system_reminder(text):
                dropped_system += 1
                continue

            # Strip embedded system-reminder blocks but keep the rest
            text = _strip_system_reminders(text)
            if not text:
                dropped_system += 1
                continue

            if role == "user":
                group = _detect_wa_group(text)
                if group:
                    lines.append(f"[WA group: {group}]")
                lines.append(f"USER: {text}")
                lines.append("")
                msg_count += 1
            elif role == "assistant":
                lines.append(f"ASSISTANT: {text}")
                lines.append("")
                msg_count += 1

        elif isinstance(content, list):
            parts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                bt = block.get("type", "?")

                if bt == "thinking":
                    dropped_thinking += 1
                    continue
                elif bt == "tool_result":
                    dropped_tool_results += 1
                    continue
                elif bt == "tool_use":
                    parts.append(_compress_tool_use(block))
                elif bt == "text":
                    text = block.get("text", "").strip()
                    if not text:
                        continue
                    if _is_pure_system_reminder(text):
                        dropped_system += 1
                        continue
                    text = _strip_system_reminders(text)
                    if text:
                        parts.append(text)

            # Collapse consecutive tool one-liners into a single block
            tool_lines = [p for p in parts if p.startswith("[")]
            text_parts = [p for p in parts if not p.startswith("[")]

            output_parts = []
            if text_parts:
                output_parts.extend(text_parts)
            if tool_lines:
                output_parts.append("\n".join(tool_lines))

            if output_parts:
                prefix = "ASSISTANT" if role == "assistant" else "USER"
                combined = "\n".join(output_parts)
                lines.append(f"{prefix}: {combined}")
                lines.append("")
                msg_count += 1

    # Stats footer
    lines.append("---")
    lines.append(f"# Stats: {msg_count} messages kept, {dropped_thinking} thinking blocks dropped,")
    lines.append(f"# {dropped_tool_results} tool results dropped, {dropped_system} system reminders dropped")

    output_text = "\n".join(lines)

    with open(output_path, "w") as f:
        f.write(output_text)

    return {
        "input": str(input_path),
        "output": str(output_path),
        "raw_messages": len(messages),
        "kept_messages": msg_count,
        "dropped_thinking": dropped_thinking,
        "dropped_tool_results": dropped_tool_results,
        "dropped_system": dropped_system,
        "input_bytes": Path(input_path).stat().st_size,
        "output_bytes": Path(output_path).stat().st_size,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input.json> [output.txt]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    stats = compress_session(input_file, output_file)
    ratio = stats["output_bytes"] / stats["input_bytes"] * 100

    print(f"Done: {stats['raw_messages']} → {stats['kept_messages']} messages")
    print(f"Size: {stats['input_bytes']:,} → {stats['output_bytes']:,} bytes ({ratio:.0f}%)")
    print(f"Dropped: {stats['dropped_thinking']} thinking, {stats['dropped_tool_results']} tool results, {stats['dropped_system']} system reminders")
    print(f"Output: {stats['output']}")
