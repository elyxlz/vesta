"""Bubble lint: reject wall-of-text chat sends before they reach the app.

Mirrors the telegram/whatsapp CLI bubble lint so app-chat enforces the same
"short bubbles, one thought per send" rule at send time. A rule the agent only
has to *remember* is the weakest enforcement and keeps regressing into one
multi-sentence block that reads like an assistant, not a person. Checking at
send time, where every send passes through, makes it structural: a wall is
rejected with the reason, so the agent re-sends as several short calls.

The single bypass is ``--longform``, for genuine reference material the user
asked for (a brief, a code block, a list).
"""

import re

# A bubble is "a few words to one line, rarely two" (personality SKILL.md).
BUBBLE_MAX_CHARS = 220  # a genuinely long single bubble
BUBBLE_MAX_SENTENCES = 2  # 3+ sentence-enders in one send = a paragraph, split it

_URL_RE = re.compile(r"https?://\S+")  # urls
_DECIMAL_RE = re.compile(r"\b\d+[.,]\d+\b")  # decimals: 8.6, 86,5
_INITIALISM_RE = re.compile(r"\b(?:[A-Za-z]\.){2,}")  # initialisms: W.A.S.T.E., U.K.
_ABBR_RE = re.compile(
    r"\b(?:mr|mrs|ms|dr|prof|st|vs|etc|e\.g|i\.e|a\.m|p\.m|u\.k|u\.s|approx|no|fig)\.",
    re.IGNORECASE,
)
_ENDER_RE = re.compile(r"[.!?]+")


def _strip_protected(text: str) -> str:
    """Blank out spans whose '.', '?' or '!' are not sentence boundaries."""
    for rx in (_URL_RE, _DECIMAL_RE, _INITIALISM_RE, _ABBR_RE):
        text = rx.sub(" ", text)
    return text


def count_sentences(text: str) -> int:
    """Count sentence-ending runs: terminal punctuation followed by whitespace
    then an ASCII alphanumeric, or sitting at the end of the text."""
    cleaned = _strip_protected(text).strip()
    count = 0
    for match in _ENDER_RE.finditer(cleaned):
        rest = cleaned[match.end() :]
        if rest == "":
            count += 1
            continue
        trimmed = rest.lstrip(" \t\r\n\v\f")
        if len(trimmed) == len(rest) or trimmed == "":
            continue  # no whitespace gap, or nothing after it
        first = trimmed[0]
        if first.isascii() and first.isalnum():
            count += 1
    return count


def bubble_lint_reason(message: str) -> str:
    """Return a non-empty explanation when message is a wall (too many
    characters, or too many sentences in one bubble), or "" if it passes."""
    n_chars = len(message)
    n_sent = count_sentences(message)
    if n_chars <= BUBBLE_MAX_CHARS and n_sent <= BUBBLE_MAX_SENTENCES:
        return ""
    why = []
    if n_chars > BUBBLE_MAX_CHARS:
        why.append(f"{n_chars} chars")
    if n_sent > BUBBLE_MAX_SENTENCES:
        why.append(f"{n_sent} sentences in one bubble")
    return (
        "bubble lint: this send is a wall (" + ", ".join(why) + "). texting rule: short bubbles, one thought per send. split it into "
        "several separate send calls, a beat between each, one idea each. if this "
        "is genuine reference material (a brief, a code block, a list they asked "
        "for), resend the same command with --longform to bypass."
    )
