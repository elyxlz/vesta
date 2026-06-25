#!/usr/bin/env python3
"""PreToolUse lint: catch wall-of-text chat sends BEFORE they reach the user.

Why this exists: the "text in short bubbles, one thought per send" rule lived only in
the personality preset (a rule I'm supposed to enact every message) and I kept regressing
to single multi-sentence blocks. Elio's call (Jun25): don't auto-split mechanically (that
robs me of choosing the break points), warn me instead, like the em-dash lint does, so I
fix it myself and actually learn. This is that warning, at send time.

Mechanism: a PreToolUse hook on Bash. If the command is a telegram/whatsapp `send` with an
inline --message that's a wall (too long, or 3+ sentences crammed in one bubble), exit 2.
Exit 2 on PreToolUse blocks the call and feeds stderr back to the model, so I re-send as
several short calls. Opt out for genuine reference material (the morning brief, code, a list)
with `--message-file` or a `# longform` marker in the command.

Deliberately conservative: it only sees the LITERAL inline text, so loop/array sends (already
split) and --message-file sends (reference) pass untouched. It only fires on the exact
regression pattern: one send, one long literal blob.
"""

import json
import re
import sys

# Thresholds. A bubble is "a few words to one line, rarely two" (personality SKILL.md).
MAX_CHARS = 220  # a genuinely long single bubble
MAX_SENTENCES = 2  # 3+ sentence-enders in one send = a paragraph, split it

# Abbreviations whose dot must NOT count as a sentence end.
_ABBR = r"(?:mr|mrs|ms|dr|prof|st|vs|etc|e\.g|i\.e|a\.m|p\.m|u\.k|u\.s|approx|no|fig)"


def _strip_protected(text: str) -> str:
    """Blank out things whose '.' / '?' / '!' are not sentence boundaries."""
    text = re.sub(r"https?://\S+", " ", text)  # urls
    text = re.sub(r"\b\d+[.,]\d+\b", " ", text)  # decimals: 8.6, 86,5
    text = re.sub(r"\b(?:[A-Za-z]\.){2,}", " ", text)  # initialisms: W.A.S.T.E., U.K.
    text = re.sub(_ABBR + r"\.", " ", text, flags=re.I)  # known abbreviations
    return text


def _count_sentences(text: str) -> int:
    cleaned = _strip_protected(text)
    # a sentence break = terminal punctuation followed by space + a letter/digit, OR end of string
    breaks = re.findall(r"[.!?]+(?:\s+(?=[A-Za-z0-9])|$)", cleaned.strip())
    return len(breaks)


def _extract_message(cmd: str):
    """Pull the inline --message "..." / --message '...' literal, if present and static."""
    if "--message-file" in cmd or "# longform" in cmd or "--raw" in cmd:
        return None  # opt-out: reference material
    m = re.search(r"--message(?:=|\s+)(['\"])(.*?)(?<!\\)\1", cmd, re.S)
    if not m:
        return None
    val = m.group(2)
    # Loop/array or command-substitution sends aren't a single static literal; skip them.
    if "$" in val or "`" in val:
        return None
    return val


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if data.get("tool_name") != "Bash":
        sys.exit(0)
    cmd = data.get("tool_input", {}).get("command", "")
    if not re.search(r"\b(telegram|whatsapp)\b.*\bsend\b", cmd):
        sys.exit(0)
    msg = _extract_message(cmd)
    if msg is None:
        sys.exit(0)
    n_sent = _count_sentences(msg)
    n_chars = len(msg)
    if n_chars <= MAX_CHARS and n_sent <= MAX_SENTENCES:
        sys.exit(0)
    why = []
    if n_chars > MAX_CHARS:
        why.append(f"{n_chars} chars")
    if n_sent > MAX_SENTENCES:
        why.append(f"{n_sent} sentences in one bubble")
    sys.stderr.write(
        "BUBBLE LINT: this chat send is a wall (" + ", ".join(why) + "). "
        "Texting rule: short bubbles, one thought per send. Split it into several "
        "separate `send` calls (a beat between each), one idea each. "
        "If this is genuine reference material (the morning brief, a code block, a list "
        "they asked for), resend the SAME command with a trailing `# longform` to bypass.\n"
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
