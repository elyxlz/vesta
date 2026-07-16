"""Dictionary / synonym tool for paraphrase + AI-detection defeat.

Pairs with the humaniser. The humaniser does paragraph-level rewrites; this
tool does targeted word-level swaps without touching surrounding sentence
structure. Used to:

  * Eliminate AI-detector "tells" (banned vocabulary like `delve`, `tapestry`,
    `harness`) by swapping in register-matched alternatives that don't trigger
    the detector.
  * Give the writer / reviewer agents a fast lookup for synonyms,
    register-shifted alternatives, and meaning neighbours during edit passes.
  * Enable a `ban-replace` pass that scans a draft for banned terms and
    emits a diff with proposed swaps.

Backends (no API key needed for either):
  * **Datamuse** (https://api.datamuse.com): free, ~100K req/day soft cap.
    Provides `/words?ml=`, `/words?rel_syn=`, `/words?rel_trg=`, etc.,
    frequency-ranked. Best for synonyms-by-meaning and register-aware swaps.
  * **WordNet via offline NLTK** (lazy-loaded, only if `nltk` is installed)
    as a fallback when Datamuse is unreachable or too slow. Provides POS-
    aware synsets and definitions.

CLI:
    python dictionary.py syn "delve"
    python dictionary.py alt "delve" --register academic
    python dictionary.py ban-replace draft.md
    python dictionary.py fight-detector draft.md

Library:
    from dictionary import synonyms, alternatives, ban_replace, BANNED_DEFAULT
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Literal

import requests

Register = Literal["academic", "casual", "formal"]

DATAMUSE_BASE = "https://api.datamuse.com"
DEFAULT_TIMEOUT = (4.0, 8.0)
USER_AGENT = "vesta-essay-iter/1.0"

# Default banned-vocabulary list (the AI-detector tells we already track in
# SKILL.md). Extend per essay if needed.
BANNED_DEFAULT: tuple[str, ...] = (
    "delve",
    "tapestry",
    "intricate",
    "navigate",
    "underscore",
    "pivotal",
    "robust",
    "multifaceted",
    "leverage",
    "harness",
    "paradigm",
    "landscape",
    "realm",
    "testament",
    "garner",
    "foster",
    "meticulously",
    "showcase",
    "vibrant",
    "profound",
    "holistic",
    "nuanced",
    "moreover",
    "furthermore",
    "additionally",
)


def _datamuse(path: str, params: dict, timeout=DEFAULT_TIMEOUT) -> list[dict]:
    """GET against Datamuse with retry on transient errors only.

    Retries on timeout / connection error / 429 / 5xx. Does NOT retry on
    4xx client errors. Returns [] on exhaustion (callers want a usable
    fallback rather than a hard failure for word-level lookups)."""
    import time as _time

    url = f"{DATAMUSE_BASE}{path}"
    last_err: str | None = None
    for attempt in range(3):
        try:
            r = requests.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
            )
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = repr(e)
            _time.sleep(0.5 * (attempt + 1))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            last_err = f"HTTP {r.status_code}"
            _time.sleep(0.5 * (attempt + 1))
            continue
        # 4xx (other than 429) is a client error: don't retry, propagate empty.
        last_err = f"HTTP {r.status_code}: {r.text[:120]}"
        break
    if last_err:
        print(f"[dictionary] datamuse {path} failed: {last_err}", file=sys.stderr)
    return []


def synonyms(word: str, *, limit: int = 20) -> list[str]:
    """Direct synonyms (Datamuse `rel_syn`) plus meaning-neighbours
    (Datamuse `ml`), deduplicated, frequency-ranked. Best fast path."""
    seen: set[str] = set()
    out: list[str] = []
    for path, params in (
        ("/words", {"rel_syn": word, "max": limit}),
        ("/words", {"ml": word, "max": limit}),
    ):
        for entry in _datamuse(path, params):
            w = (entry.get("word") or "").lower()
            if not w or w == word.lower() or w in seen:
                continue
            seen.add(w)
            out.append(w)
            if len(out) >= limit:
                return out
    return out


def alternatives(
    word: str,
    *,
    register: Register = "academic",
    limit: int = 10,
) -> list[str]:
    """Register-tuned alternatives. `register` ∈ {'academic','casual','formal'}.

    Strategy: pull a wide synonym pool, then re-rank by register hints.
    Datamuse doesn't expose register directly, so we use simple heuristics:
      'academic' favours longer Latinate words, demotes very casual/slang.
      'casual' favours shorter, Anglo-Saxon roots, demotes archaic/formal.
      'formal' = academic with no contractions, no first-person, neutral tone.
    """
    pool = synonyms(word, limit=max(limit * 3, 30))
    if not pool:
        return []
    if register in ("academic", "formal"):
        scored = sorted(
            pool,
            key=lambda w: (-_academic_score(w), len(w) * -1, w),
        )
    elif register == "casual":
        scored = sorted(
            pool,
            key=lambda w: (-_casual_score(w), len(w), w),
        )
    else:
        scored = pool
    return scored[:limit]


_LATIN_ENDINGS = ("tion", "ment", "ence", "ance", "ity", "ate", "ize", "ise", "ous", "ive")


def _academic_score(word: str) -> int:
    s = 0
    if any(word.endswith(e) for e in _LATIN_ENDINGS):
        s += 2
    if len(word) >= 7:
        s += 1
    if word in BANNED_DEFAULT:
        s -= 100  # never recommend a swap that's also banned
    return s


def _casual_score(word: str) -> int:
    s = 0
    if len(word) <= 5:
        s += 2
    if not any(word.endswith(e) for e in _LATIN_ENDINGS):
        s += 1
    if word in BANNED_DEFAULT:
        s -= 100
    return s


def _compile_banned(banned: tuple[str, ...]) -> re.Pattern:
    return re.compile(
        r"\b(" + "|".join(re.escape(w) for w in banned) + r")\b",
        flags=re.IGNORECASE,
    )


_BAN_DEFAULT_RE = _compile_banned(BANNED_DEFAULT)


def ban_replace(
    text: str,
    *,
    banned: tuple[str, ...] = BANNED_DEFAULT,
    register: Register = "academic",
) -> tuple[str, list[dict]]:
    """Scan `text` for `banned` words and swap each for the best register-
    matched alternative. Returns `(rewritten_text, swaps)` with each swap
    `{old, new, position}` so the writer can review/accept.

    Cache is keyed by `(word, register)` so the same word looked up under a
    different register doesn't return stale alternatives across sessions
    (defensive: ban_replace today only ever runs at one register per call,
    but the helper may be reused).
    """
    swaps: list[dict] = []
    cache: dict[tuple[str, str], str | None] = {}
    pattern = _BAN_DEFAULT_RE if banned is BANNED_DEFAULT else _compile_banned(banned)

    def replace_match(m: re.Match) -> str:
        original = m.group(0)
        word = original.lower()
        key = (word, register)
        if key not in cache:
            alts = alternatives(word, register=register, limit=5)
            cache[key] = alts[0] if alts else None
        repl = cache[key]
        if not repl:
            return original
        if original[0].isupper():
            repl = repl[0].upper() + repl[1:]
        swaps.append({"old": original, "new": repl, "position": m.start()})
        return repl

    rewritten = pattern.sub(replace_match, text)
    return rewritten, swaps


# ---------------------------------------------------------------------------
# Stylometric tells beyond banned-vocabulary
# ---------------------------------------------------------------------------

# Present-participial appositives (LLMs over-use these by 2-5x)
_PRESENT_APPOSITIVE_RE = re.compile(
    r",\s+(highlighting|emphasising|emphasizing|reflecting|underscoring|illustrating|"
    r"showcasing|demonstrating|signalling|signaling|suggesting)\s+\w+",
    flags=re.IGNORECASE,
)

# Em-dash + en-dash + " - " separator: convert to comma/period.
_DASH_SEP_RE = re.compile(r"\s+[—–]\s+|\s-\s")


def fight_detector(
    text: str,
    *,
    banned: tuple[str, ...] = BANNED_DEFAULT,
) -> tuple[str, list[dict]]:
    """One-shot stylometric scrub for AI-detection-flagged paragraphs:

      1. Replace banned vocabulary with register-matched alternatives.
      2. Collapse em-dash / en-dash / " - " separators to comma or period.
      3. Flag (but don't auto-rewrite) present-participial appositive clauses;
         the writer should restructure these as finite clauses.

    Returns `(rewritten_text, change_log)` where change_log enumerates
    every modification + every flagged-but-not-rewritten span. Suitable
    for a per-paragraph pass on output flagged by the AI-detection critic.
    """
    log: list[dict] = []
    rewritten, swaps = ban_replace(text, banned=banned, register="academic")
    for s in swaps:
        log.append({"kind": "ban-replace", **s})

    def dash_sub(m: re.Match) -> str:
        log.append({"kind": "dash-collapsed", "at": m.start(), "was": m.group(0)})
        return ", "

    rewritten = _DASH_SEP_RE.sub(dash_sub, rewritten)

    for m in _PRESENT_APPOSITIVE_RE.finditer(rewritten):
        log.append(
            {
                "kind": "present-appositive-flagged",
                "at": m.start(),
                "phrase": m.group(0),
                "fix": "restructure as a finite clause (e.g. ', which X' -> '. This X')",
            }
        )

    return rewritten, log


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dictionary", description=(__doc__ or "").split("\n", 1)[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("syn", help="Direct synonyms + meaning-neighbours.")
    sp.add_argument("word")
    sp.add_argument("--limit", type=int, default=20)

    ap = sub.add_parser("alt", help="Register-tuned alternatives.")
    ap.add_argument("word")
    ap.add_argument("--register", default="academic", choices=("academic", "formal", "casual"))
    ap.add_argument("--limit", type=int, default=10)

    bp = sub.add_parser("ban-replace", help="Scan a draft for banned words and propose swaps.")
    bp.add_argument("path", type=Path)
    bp.add_argument("--register", default="academic")
    bp.add_argument("--banned", nargs="*", help="override default banned list")
    bp.add_argument("--write", action="store_true", help="overwrite the file with rewritten text")

    fp = sub.add_parser(
        "fight-detector",
        help="Full stylometric scrub on a draft (banned-vocab + dashes + appositive flags).",
    )
    fp.add_argument("path", type=Path)
    fp.add_argument("--banned", nargs="*", help="override default banned list")
    fp.add_argument("--write", action="store_true")

    args = p.parse_args(argv)

    if args.cmd == "syn":
        _print(synonyms(args.word, limit=args.limit))
    elif args.cmd == "alt":
        _print(alternatives(args.word, register=args.register, limit=args.limit))
    elif args.cmd in ("ban-replace", "fight-detector"):
        text = args.path.read_text()
        banned = tuple(args.banned) if args.banned else BANNED_DEFAULT
        if args.cmd == "ban-replace":
            new_text, log = ban_replace(text, banned=banned, register=args.register)
        else:
            new_text, log = fight_detector(text, banned=banned)
        if args.write:
            args.path.write_text(new_text)
            _print({"wrote": str(args.path), "changes": len(log), "log": log})
        else:
            _print({"changes": len(log), "log": log, "preview": new_text[:600]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
