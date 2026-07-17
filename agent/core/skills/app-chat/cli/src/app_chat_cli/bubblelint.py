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

_URL_RE = re.compile(r"https?://\S+")  # urls
_DECIMAL_RE = re.compile(r"\b\d+[.,]\d+\b")  # decimals: 8.6, 86,5
_INITIALISM_RE = re.compile(r"\b(?:[A-Za-z]\.){2,}")  # initialisms: W.A.S.T.E., U.K.
_ABBR_RE = re.compile(
    r"\b(?:mr|mrs|ms|dr|prof|st|vs|etc|e\.g|i\.e|a\.m|p\.m|u\.k|u\.s|approx|no|fig)\.",
    re.IGNORECASE,
)
_ELLIPSIS_RE = re.compile(r"\.{3,}")  # ellipsis: a texting beat, not a full stop
_ENDER_RE = re.compile(r"[.!?]+")

_SPACE = " \t\r\n\v\f"


def _strip_protected(text: str) -> str:
    """Blank out spans whose '.', '?' or '!' are not sentence boundaries."""
    for rx in (_URL_RE, _DECIMAL_RE, _INITIALISM_RE, _ABBR_RE, _ELLIPSIS_RE):
        text = rx.sub(" ", text)
    return text


def text_after_full_stop(text: str) -> bool:
    """True when a '.', '!' or '?' has anything after it: the tell of a second
    thought crammed into the same bubble.

    A mark only reads as a full stop when whitespace follows it, so "main.py"
    and "example.com" stay single thoughts.
    """
    cleaned = _strip_protected(text).strip()
    for match in _ENDER_RE.finditer(cleaned):
        rest = cleaned[match.end() :]
        trimmed = rest.lstrip(_SPACE)
        if trimmed == "" or len(trimmed) == len(rest):
            continue  # the mark ends the bubble, or no whitespace gap follows it
        return True
    return False


def bubble_lint_reason(message: str) -> str:
    """Return a non-empty explanation when message is a wall (too many
    characters, or text carrying on past a full stop), or "" if it passes."""
    n_chars = len(message)
    why = []
    if n_chars > BUBBLE_MAX_CHARS:
        why.append(f"{n_chars} chars")
    if text_after_full_stop(message):
        why.append("text after a full stop")
    if not why:
        return ""
    return (
        "bubble lint: this send is a wall (" + ", ".join(why) + "). texting rule: short bubbles, one thought per send, and don't use "
        "full stops at all. split it into several separate send calls, a beat between "
        "each, one idea each. if this is genuine reference material (a brief, a code "
        "block, a list they asked for), resend the same command with --longform to "
        "bypass."
    )
