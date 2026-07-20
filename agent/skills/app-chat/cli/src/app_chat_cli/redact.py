"""Secret-scrub patterns for the app-chat store, mirroring the dream skill's events.db scrubber
(agent/skills/dream/scripts/redact_secrets.py). That script is the canonical owner of the pattern set;
this skill is a standalone uv project and cannot import across the skill-project boundary without a
sys.path hack, so the patterns are mirrored here and MUST stay in sync with that owner. User-typed
messages now live in this store, out of the events.db scrubber's reach, so `app-chat redact` gives the
store the same scrub."""

import json
import re

type JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]

REDACTED = "[REDACTED]"

PATTERNS = [
    r"sk-[a-zA-Z0-9_-]{20,}",
    r"[sr]k_(?:live|test)_[0-9a-zA-Z]{20,}",
    r"xox[bp]-[0-9A-Za-z-]+",
    r"gh[posr]_[A-Za-z0-9]{36,}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"glpat-[A-Za-z0-9_-]{20,}",
    r"(?-i:AKIA[0-9A-Z]{16})",
    r"PMAK-[A-Za-z0-9-]{20,}",
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}",
    r"BEGIN [A-Z ]+ PRIVATE KEY",
    r"(?:password|secret|api[_-]?key)[ ]*\\?[\"':=]+[ ]*\\?[\"']?[^ \"'\\]{4,}",
    r"(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|redis)://[^ \"']+",
]
REGEX = re.compile("|".join(PATTERNS), re.IGNORECASE)

# Scoped to the sk- (hyphen) pattern only: its body collides with English-word URL slugs
# ("sk-hynix-raises-full-year-guidance"), so a short all-lowercase hyphen/underscore run is a slug,
# not a key. Other families are hex/base62 and never slug-checked. Mirrors redact_secrets.py.
_SLUG_PREFIX = re.compile(r"^sk-")


def _looks_like_word_slug(token: str) -> bool:
    body, matched = _SLUG_PREFIX.subn("", token)
    if matched == 0:
        return False
    if body != body.lower():
        return False
    segs = [s for s in re.split(r"[-_]", body) if s]
    return len(segs) >= 2 and all(len(s) < 16 for s in segs)


def mask(match: re.Match[str]) -> str:
    """Replace a real hit with the placeholder. An already-scrubbed span is left untouched so a re-run
    is idempotent (never re-flags or mangles `password=[REDACTED]`); a word-slug false positive on the
    sk- pattern is left alone. `redact` scrubs every hit unattended, so the slug filter guards it here
    (redact_secrets.py filters slugs only in its interactive scan, before the manual scrub)."""
    token = match.group(0)
    if REDACTED in token or _looks_like_word_slug(token):
        return token
    return REDACTED


def _redact_json(value: JsonValue) -> JsonValue:
    """Apply the mask regex to every string inside a parsed JSON value. Redacting the decoded
    structure (not the serialized blob) keeps the re-serialized event valid JSON."""
    if isinstance(value, str):
        return REGEX.sub(mask, value)
    if isinstance(value, list):
        return [_redact_json(v) for v in value]
    if isinstance(value, dict):
        return {k: _redact_json(v) for k, v in value.items()}
    return value


def redact_data(data: str) -> str | None:
    """The row's JSON `data` blob with every secret pattern hit masked, or None when nothing matched
    (so the store leaves an untouched row unwritten). A slug false-positive on the sk- pattern is left
    alone. Falls back to a raw text sub for a non-JSON payload (nothing to keep structurally valid)."""
    try:
        obj: JsonValue = json.loads(data)
    except (json.JSONDecodeError, TypeError):
        new = REGEX.sub(mask, data)
        return new if new != data else None
    new_obj = _redact_json(obj)
    if new_obj == obj:
        return None
    return json.dumps(new_obj)
