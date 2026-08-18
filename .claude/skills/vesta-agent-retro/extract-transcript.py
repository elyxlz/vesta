#!/usr/bin/env python3
"""Render a redacted slice of a Vesta agent's Claude session transcript.

Runs INSIDE the agent container, where the 150MB+ session .jsonl is a local file.
Reads env: JSONL (path to the session transcript), SINCE / UNTIL (ISO timestamps,
inclusive, compared as strings so pass them zero-padded UTC). Writes the transcript
to stdout and a one-line leak check to stderr.

The .jsonl is the ONLY place tool results live. The agent's events.db has thinking,
tool calls, and messages, but records only that a tool ran, never its output.
"""

import json
import os
import pathlib
import re
import sys

JSONL = os.environ["JSONL"]
SINCE = os.environ["SINCE"]
UNTIL = os.environ["UNTIL"]

# One secret can sit in a pasted user message, a tool_use input (an env-file heredoc),
# and a tool_result at once, so redact every rendered field, not just chat.
_SECRET_PATTERNS = [
    (re.compile(r"wak_[A-Za-z0-9_\-]{6,}"), "wak_REDACTED"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "sk-REDACTED"),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|key[_-]?secret|secret|token|password|passwd|authorization|bearer)"
            r"(['\"]?\s*[=:]\s*['\"]?)([^\s'\",}]+)"
        ),
        r"\1\2REDACTED",
    ),
]


def redact(value):
    text = value if isinstance(value, str) else json.dumps(value)
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def in_window(ts):
    return bool(ts) and SINCE <= ts <= UNTIL


def hhmm(ts):
    return ts[11:19] if len(ts) >= 19 else ts


def result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            else:
                parts.append(json.dumps(block))
        return "\n".join(parts)
    return json.dumps(content)


def render(out):
    with pathlib.Path(JSONL).open(encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = entry.get("timestamp", "")
            if not in_window(ts) or entry.get("type") not in ("user", "assistant"):
                continue
            message = entry.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str):
                body = re.sub(r"^\[Current time:[^\]]*\]\s*", "", redact(content).strip())
                if body:
                    out.append(f"\n[{hhmm(ts)}] USER/CONTEXT: {body[:900]}")
                continue
            if not isinstance(content, list):
                continue
            for block in content:
                kind = block.get("type")
                if kind == "thinking":
                    out.append(f"[{hhmm(ts)}] THINKING:")
                    out.append(redact(block.get("thinking", "")).rstrip())
                elif kind == "text":
                    out.append(f"[{hhmm(ts)}] ASSISTANT: {redact(block.get('text', '')).strip()}")
                elif kind == "tool_use":
                    inp = block.get("input", {})
                    cmd = inp["command"] if isinstance(inp, dict) and "command" in inp else json.dumps(inp)
                    out.append(f"[{hhmm(ts)}] TOOL CALL [{block.get('name', '')}]:")
                    out.append(redact(cmd)[:2000].rstrip())
                elif kind == "tool_result":
                    out.append(f"[{hhmm(ts)}]   -> RESULT: {redact(result_text(block.get('content')))[:3000].rstrip()}")


def main():
    out = []
    render(out)
    text = "\n".join(out) + "\n"
    sys.stdout.write(text)
    leaks = re.findall(r"wak_[A-Za-z0-9]{20,}", text) + re.findall(r"sk-[A-Za-z0-9]{24,}", text)
    sys.stderr.write(f"leak-check: {len(leaks)} possible unredacted secret(s); {len(out)} lines rendered\n")


if __name__ == "__main__":
    main()
