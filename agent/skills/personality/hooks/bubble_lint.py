#!/usr/bin/env python3
"""PreToolUse lint: catch wall-of-text chat sends BEFORE they reach the user.

Why this exists: the "text in short bubbles, one thought per send" rule lives in the
personality preset, but a rule the agent must remember to enact every message is easy to
regress on (a single multi-sentence block slips out). The design choice: don't auto-split
mechanically (that robs the agent of choosing its own break points); warn at send time
instead, like an em-dash lint, so the agent fixes it by hand and actually learns.

Mechanism: a PreToolUse hook on Bash. If the command is a telegram/whatsapp `send` with an
inline --message that's a wall (too long, or 2+ sentences crammed in one bubble), exit 2.
Exit 2 on PreToolUse blocks the call and feeds stderr back to the model, so it re-sends as
several short calls. Opt out for genuine reference material (a morning brief, code, a list)
with `--message-file` or a `# longform` marker in the command.

A command may contain several `send` calls; each is linted independently and the error
names the specific offender(s), so a batch of clean bubbles passes and only the flagged
send needs re-splitting (a PreToolUse hook is all-or-nothing on the command, so any wall
still blocks the whole call, but the good bubbles can be resent verbatim).

Deliberately conservative: it only sees the LITERAL inline text, so loop/array sends (already
split) and --message-file sends (reference) pass untouched.

The thresholds below are tunable to how terse a given user's style is: MAX_SENTENCES=0 is the
strict "one thought per bubble" default; raise it to allow more sentences per bubble.
"""

import json
import re
import sys

# Thresholds. A bubble is "a few words to one line, rarely two" (personality SKILL.md).
MAX_CHARS = 220  # a genuinely long single bubble
MAX_SENTENCES = 0  # internal sentence breaks allowed: 0 = one thought per bubble; any mid-bubble break = 2+ beats, split it

# Abbreviations whose dot must NOT count as a sentence end.
_ABBR = r"(?:mr|mrs|ms|dr|prof|st|vs|etc|e\.g|i\.e|a\.m|p\.m|u\.k|u\.s|approx)"


def _strip_protected(text: str) -> str:
    """Blank out things whose '.' / '?' / '!' are not sentence boundaries."""
    text = re.sub(r"https?://\S+", " ", text)  # urls
    text = re.sub(r"\b\d+[.,]\d+\b", " ", text)  # decimals: 8.6, 86,5
    text = re.sub(r"\b(?:[A-Za-z]\.){2,}", " ", text)  # initialisms: W.A.S.T.E., U.K.
    text = re.sub(_ABBR + r"\.", " ", text, flags=re.I)  # known abbreviations
    return text


def _count_sentences(text: str) -> int:
    """Count INTERNAL sentence breaks: terminal punctuation followed by more text.

    This is beats-minus-one. A trailing '.' at end of string is NOT a break (one
    complete sentence = 0 breaks = fine). "919 is green. ready for u" has 1 break
    (the second clause needs no period to count), so it's two beats and gets split.
    """
    cleaned = _strip_protected(text)
    breaks = re.findall(r"[.!?]+\s+(?=[A-Za-z0-9])", cleaned.strip())
    return len(breaks)


def _extract_messages(cmd: str):
    """Pull every inline chat message literal from the command, both forms:

      --message "..."                          (flag form)
      telegram send "<contact>" "..."          (positional form)

    Returns a list of static literals to lint. Skips reference/opt-out and dynamic sends.
    send-file / send-voice / send-chat-action carry paths, not text, so they're excluded.
    """
    if "--longform" in cmd or "--message-file" in cmd or "# longform" in cmd or "--raw" in cmd:
        return []  # opt-out: reference material (the canonical flag lives outside --message so it can't leak)
    msgs = []
    # Flag form: --message "..." / --message='...'
    for m in re.finditer(r"--message(?:=|\s+)(['\"])(.*?)(?<!\\)\1", cmd, re.S):
        msgs.append(m.group(2))
    # Positional form: `send "<contact>" "<message>"` or `send-message "<contact>" "<message>"`.
    # `send(?!-)` excludes send-file / send-voice / send-chat-action (those args are paths, not text).
    for m in re.finditer(
        r"(?:\bsend-message\b|\bsend\b(?!-))\s+(['\"]).*?(?<!\\)\1\s+(['\"])(.*?)(?<!\\)\2",
        cmd,
        re.S,
    ):
        msgs.append(m.group(3))
    # Loop/array or command-substitution sends aren't a single static literal; skip those.
    return [v for v in msgs if "$" not in v and "`" not in v]


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
    msgs = _extract_messages(cmd)
    if not msgs:
        sys.exit(0)

    # Lint each send independently and report per-send, so a batch of several sends
    # in one command points at the *specific* offender(s) instead of failing opaquely.
    # (A PreToolUse hook is all-or-nothing on the command, so any wall still blocks the
    # whole call; naming the bad line lets the good bubbles be kept verbatim on the resend.)
    verdicts = []
    n_walls = 0
    for i, msg in enumerate(msgs, 1):
        reasons = []
        n_chars = len(msg)
        n_sent = _count_sentences(msg)
        if n_chars > MAX_CHARS:
            reasons.append(f"{n_chars} chars")
        if n_sent > MAX_SENTENCES:
            reasons.append(f"{n_sent + 1} beats in one bubble")
        preview = msg if len(msg) <= 60 else msg[:57] + "..."
        label = f"send {i}" if len(msgs) > 1 else "this send"
        if reasons:
            n_walls += 1
            verdicts.append(f'  x {label} is a wall ({", ".join(reasons)}): "{preview}"')
        else:
            verdicts.append(f'  ok {label}: "{preview}"')
    if n_walls == 0:
        sys.exit(0)

    only = "the flagged send" if len(msgs) == 1 else f"only the {n_walls} flagged send(s), keep the ok ones verbatim"
    sys.stderr.write(
        "BUBBLE LINT: a chat send is a wall. Fix " + only + ":\n" + "\n".join(verdicts) + "\n"
        "Texting rule: short bubbles, one thought per send. Split each flagged send into "
        "several separate `send` calls (a beat between each), one idea each. "
        "If a flagged one is genuine reference material (a morning brief, a code block, a "
        "list they asked for), resend it with the `--longform` flag (e.g. `telegram send ... "
        '--message "..." --longform`) to bypass. Use the flag, never put the word longform '
        "inside --message.\n"
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
