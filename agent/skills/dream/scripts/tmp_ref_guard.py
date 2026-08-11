#!/usr/bin/env python3
"""PreToolUse gate: refuse to write a /tmp path into a task's durable notes.

A task note is read days or weeks after it is written, and /tmp does not live that long: it is
cleared on reboot and by routine cleanup. A note pointing into /tmp therefore decays into a
confident reference to nothing, and the gap only surfaces when someone finally acts on the task and
finds the artefact gone. Detecting those references afterwards cannot recover them, because the
files are already deleted by the time any sweep runs. The one moment at which the loss is
preventable is the moment the path gets written down, which is here.

WHAT IT DOES NOT FLAG, deliberately:

  - Any file outside a task's metadata directory. Scratch work in /tmp is correct and normal; the
    bug is only ever a durable note POINTING at scratch work.
  - A /tmp path that is already in the file. Editing a note that mentions a dead path, which is
    exactly what repairing one of these looks like, must not be blocked by the mention itself.
  - Prose recording that a path is gone. If the added text says the reference is dead or was
    recovered, that is the repair, not the offence.

FAIL-OPEN: an unreadable payload, an unexpected shape, a missing field, or any exception allows the
call. A guard against a silent data loss must never be able to wedge note-taking itself.

Usage: wired as a PreToolUse hook on `Write|Edit` (see the dream SKILL.md); `--self-test` runs its
samples. As a hook, allow and deny are both answers and both go to stdout with exit 0, which is what
Claude Code reads. `--self-test` is a probe instead: clean prints on stdout and exits 0, and a
self-test that FAILED is this command failing, so it prints on stderr and exits 1, stdout empty.
"""

import json
import pathlib
import re
import sys

TMP_PATH = re.compile(r"(?<![\w/])/tmp/[\w./-]+")
# Repair language: the added text is ABOUT a path being gone, which is the fix, not the defect.
REPAIR = re.compile(
    r"\b(no longer exists?|does not exist|already gone|(?:was|were|is|are)\s+(?:gone|dead)|dead ref"
    r"|deleted|recovered|re-?pulled|re-?saved|moved to|saved durably)\b",
    re.IGNORECASE,
)
DURABLE_HINT = (
    "Files in /tmp do not survive a reboot or a cleanup, and a task note is read days later. "
    "Write the artefact under ~/agent/data/<topic>/ and point the note there instead."
)


def metadata_dir() -> pathlib.Path:
    """Resolved from $HOME at CALL time, not bound at import, so the directory this guards is the
    one the `tasks` CLI is writing now (it takes its data dir from $HOME the same way)."""
    return pathlib.Path.home() / ".tasks" / "metadata"


def allow() -> None:
    sys.exit(0)


def deny(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


def added_text(tool: str, tool_input: dict) -> str:
    """Only the text this call INTRODUCES, so an existing dead path is never re-flagged."""
    if tool == "Write":
        return str(tool_input.get("content") or "")
    new = str(tool_input.get("new_string") or "")
    old = str(tool_input.get("old_string") or "")
    old_paths = set(TMP_PATH.findall(old))
    return "\n".join(line for line in new.splitlines() if not any(p in line for p in old_paths))


def offending_paths(text: str) -> list[str]:
    """The /tmp paths introduced on lines that are not describing a path as dead or recovered."""
    hits = []
    for line in text.splitlines():
        if REPAIR.search(line):
            continue
        hits.extend(TMP_PATH.findall(line))
    return sorted(set(hits))


def verdict(tool: str, path: str, tool_input: dict) -> str | None:
    if tool not in {"Write", "Edit"}:
        return None
    if not path or pathlib.Path(path).resolve().parent != metadata_dir():
        return None
    paths = offending_paths(added_text(tool, tool_input))
    if not paths:
        return None
    return f"This writes {', '.join(paths[:4])} into a task note. " + DURABLE_HINT


def samples() -> list[tuple[str, str, dict, bool]]:
    """(tool, file path, tool input, must flag). Built from `metadata_dir()` for the same reason it
    is a function: the samples must describe the directory this run is actually guarding."""
    note = f"{metadata_dir()}/abc.md"
    return [
        ("Write", note, {"content": "claim package saved at /tmp/claim_pack/"}, True),
        ("Write", note, {"content": "docs at ~/agent/data/claim/receipt.pdf"}, False),
        ("Write", note, {"content": "/tmp/claim_pack no longer exists, recovered"}, False),
        ("Write", "/tmp/scratch.md", {"content": "working notes at /tmp/foo/bar.pdf"}, False),
        ("Edit", note, {"old_string": "see /tmp/old/x", "new_string": "see /tmp/old/x, still"}, False),
        ("Edit", note, {"old_string": "nothing", "new_string": "now at /tmp/new/y.pdf"}, True),
        ("Bash", note, {"command": "ls /tmp/x"}, False),
        ("Write", note, {"content": "the /tmp/sar ref was dead, see ~/agent/data/sar/"}, False),
    ]


def self_test() -> list[str]:
    return [
        f"{'MISSED' if flag else 'FALSE POSITIVE'}: {tool} {str(tool_input)[:58]}"
        for tool, path, tool_input, flag in samples()
        if bool(verdict(tool, path, tool_input)) != flag
    ]


def main() -> None:
    if "--self-test" in sys.argv:
        failures = self_test()
        # One decision, taken from the outcome: a clean self-test is this command's successful
        # output and goes to stdout; a failed one is the command failing and goes to stderr, so a
        # green-looking stdout can never come out of a guard that cannot pass its own samples.
        if failures:
            print("\n".join(failures), file=sys.stderr)
            sys.exit(1)
        print(f"tmp_ref_guard: self-test clean ({len(samples())} samples)")
        sys.exit(0)

    if self_test():
        allow()  # a guard that cannot pass its own samples must not be judging anything

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        allow()
    if not isinstance(payload, dict):
        allow()

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        allow()

    try:
        reason = verdict(str(payload.get("tool_name") or ""), str(tool_input.get("file_path") or ""), tool_input)
    except Exception:
        allow()

    if reason:
        deny(reason)
    allow()


if __name__ == "__main__":
    main()
