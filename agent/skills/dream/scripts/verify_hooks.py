#!/usr/bin/env python3
"""Check that every hook wired into settings.json still parses, still runs, and still bites.

A PreToolUse guard FAILS OPEN by design: an unreadable payload, an odd shape or any exception allows
the call, so that a guard can never wedge the agent. The price of that design is that a broken guard
does not announce itself. A syntax error introduced while editing one, a script renamed or deleted,
a rewrite that dropped the deny path: all three look identical from the outside, which is to say
nothing is blocked and nothing is said. The failure mode of a safety net is that you cannot tell
from the outside whether it is still there. This is the instrument that looks.

Each wired hook is put through three questions, because passing the first two says nothing about the
third:

  1. Is it there and does it still parse?
  2. Does it wave a BENIGN call through? A guard that denies everything gets routed around, and a
     routed-around guard gets deleted.
  3. Does it DENY an input it must refuse? A guard that parses and exits 0 can still be toothless.
     Gut one to `sys.exit(0)` and only this question notices.

Question 3 needs a known-bad input per guard, which is what `must_deny()` holds. A guard with no
entry there is reported as NOT FULLY EXERCISED, by name, rather than counted as a pass: an
unexercised guard is the exact thing this script exists to find, so it must never be silently
folded into the same number as a verified one.

Discovery walks the settings STRUCTURE rather than grepping the file for `.py`. A grep misses every
hook that is not a bare python path (a `bash -lc` one-liner, a shell wrapper, `node guard.js`,
`python3 -m pkg.guard`), reads `~` and `$CLAUDE_PROJECT_DIR` paths as missing on disk, splits quoted
paths containing spaces, and matches `permissions.allow` globs like `Read(/root/agent/**/*.py)`
which are not hooks at all. Hooks it cannot reduce to one script are still counted and named,
as unchecked.

Exit 0 if nothing is broken, 1 otherwise; both are answers and print on stdout. Exit 2 means
settings.json is not there to read, which is a different finding from "no hooks wired" and does not
borrow its wording or its green exit: it goes to stderr with an empty stdout.
Report only; fixing is a judgment call.
"""

import ast
import contextlib
import json
import os
import pathlib
import shlex
import subprocess
import sys
from collections import abc

# A benign call every guard should wave through.
BENIGN = json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo hello"}})


def settings_path() -> pathlib.Path:
    """Resolved from $HOME at call time, so this reads the settings file the agent is running with
    rather than one bound at import."""
    return pathlib.Path.home() / ".claude" / "settings.json"


def must_deny() -> dict[str, str]:
    """The input each guard is SUPPOSED to refuse, keyed by script name.

    Add an entry here whenever you wire a new guard; without one, the guard can only be shown to
    parse and to allow, which is exactly the state a gutted guard is in. Use a payload that is real
    rather than illustrative: the historical call the guard was written for is the input whose
    refusal actually means something.
    """
    metadata = pathlib.Path.home() / ".tasks" / "metadata"
    return {
        "tmp_ref_guard.py": json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": str(metadata / "abcd1234.md"),
                    "content": "claim package ready, saved at /tmp/claim_pack/receipt.pdf",
                },
            }
        ),
        "blind_mutation_guard.py": json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "tasks remind delete $(tasks remind list --task X | grep -i WATCH | awk '{print $2}')"},
            }
        ),
    }


# State-dependent guards, whose answer to one input changes with what is on disk. A rolling budget
# CORRECTLY allows the first call and CORRECTLY denies the third, and only one of those can sit in
# `must_deny()`, so a fixed known-bad input cannot cover it. Register the cases here instead, as
# (label, state fixture, payload, expected verdict); the fixture is a context manager yielding the
# environment that points the guard at throwaway state it builds.
#
# BOTH DIRECTIONS ARE REQUIRED before `exercise()` calls such a guard covered. A deny-only suite
# cannot tell a working guard from one stuck on deny; an allow-only suite cannot tell teeth from no
# teeth. The allow case is the one that is easy to skip and expensive to lose: a guard that starts
# refusing ordinary work fails in the direction nobody reports.
Fixture = abc.Callable[[], contextlib.AbstractContextManager[dict[str, str]]]
STATEFUL: dict[str, list[tuple[str, Fixture, str, str]]] = {}


def hook_commands() -> list[tuple[str, str]]:
    """Every (event, command) actually wired under settings.json's `hooks` key."""
    settings = settings_path()
    if not settings.is_file():
        return []
    try:
        data = json.loads(settings.read_text())
    except json.JSONDecodeError:
        return [("PARSE", "settings.json does not parse")]
    out = []
    for event, groups in (data.get("hooks") or {}).items():
        for group in groups or []:
            for hook in (group or {}).get("hooks", []) or []:
                cmd = (hook or {}).get("command")
                if isinstance(cmd, str) and cmd.strip():
                    out.append((event, cmd.strip()))
    return out


def script_in(command: str) -> pathlib.Path | None:
    """The .py file a hook command runs, if it plainly runs one. None means 'not a bare script',
    which gets reported as unchecked rather than silently counted as a pass."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    for tok in tokens:
        if tok.endswith(".py"):
            return pathlib.Path(os.path.expandvars(tok)).expanduser()
    return None


def run(script: pathlib.Path, payload: str, env: dict[str, str] | None = None) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(script)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={**os.environ, **(env or {})},
    )
    return p.returncode, (p.stdout + p.stderr)


def decision(out: str) -> str | None:
    """The guard's ACTUAL verdict, read from the hook contract rather than from its prose.

    Searching the output for the word "deny" passes a guard that merely prints it, in a reason
    string, a log line or its own `--help`, and never reads the field the runtime acts on. That is
    a keyword match, and this file exists because a keyword match over a settings file missed a
    hook.

    Claude Code accepts two shapes: `hookSpecificOutput.permissionDecision` and a top-level
    `decision`. Both are honoured here; anything unparseable is None, which is neither a deny nor an
    allow and is reported as such.
    """
    for raw in reversed(out.strip().splitlines()):
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        specific = payload.get("hookSpecificOutput") or {}
        verdict = specific.get("permissionDecision") or payload.get("decision")
        if isinstance(verdict, str):
            return verdict.lower()
    return None


def present_and_parsing(script: pathlib.Path, event: str) -> str | None:
    """The two ways a wired guard stops existing without saying so: deleted, or no longer Python."""
    if not script.is_file():
        return f"{script} ({event}): WIRED IN settings.json BUT MISSING ON DISK"
    try:
        ast.parse(script.read_text())
    except SyntaxError as e:
        return f"{script.name}: SYNTAX ERROR line {e.lineno} ({e.msg}). Fails open, so it is silently not guarding."
    return None


def stateful_failure(script: pathlib.Path) -> str | None:
    """Run this guard's STATEFUL cases, each against the state its fixture builds, and return the
    first verdict that disagrees with what the case expects."""
    for label, fixture, payload, expected in STATEFUL.get(script.name, []):
        with fixture() as env:
            _, out = run(script, payload, env)
        verdict = decision(out) or "no parseable hook decision at all"
        if (verdict == "deny") != (expected == "deny"):
            was = "DENIED" if verdict == "deny" else f"did NOT deny ({verdict})"
            return f"{script.name}: {was} {label}, expected {expected}."
    return None


def exercise(script: pathlib.Path, event: str) -> tuple[str | None, str | None]:
    """Run one guard against a benign call, any STATEFUL cases, and a call it must refuse.

    Returns (broken reason, not-fully-exercised reason), so each guard's whole story reads top to
    bottom in one place.
    """
    still_there = present_and_parsing(script, event)
    if still_there:
        return still_there, None

    code, out = run(script, BENIGN)
    if code != 0:
        return f"{script.name}: exit {code} on a benign call: {out.strip()[:120]}", None
    if decision(out) == "deny":
        return f"{script.name}: DENIED a benign call. It over-blocks, which is how a guard gets removed.", None

    stateful = stateful_failure(script)
    if stateful:
        return stateful, None

    bad = must_deny().get(script.name)
    if bad is None:
        return None, uncovered(script.name)
    return toothless(script, bad), None


def toothless(script: pathlib.Path, bad: str) -> str | None:
    """Whether the guard let through the one input it exists to refuse. This is the question a
    gutted guard fails and the other two pass."""
    _, out = run(script, bad)
    verdict = decision(out)
    if verdict == "deny":
        return None
    got = verdict or "no parseable hook decision at all"
    return f"{script.name}: did NOT deny its known-bad input ({got}). Present but toothless."


def uncovered(name: str) -> str | None:
    """Why a guard with no known-bad input was not fully exercised, or None when its STATEFUL cases
    already show its teeth in both directions."""
    covered = {expected for _, _, _, expected in STATEFUL.get(name, [])}
    if {"allow", "deny"} <= covered:
        return None
    if not covered:
        return f"{name}: no known-bad input defined, so only parse and benign-exit were checked"
    missing = " or ".join(sorted({"allow", "deny"} - covered))
    return f"{name}: no known-bad input defined and no STATEFUL case expecting {missing}, so its teeth were not shown in both directions"


def fail(message: str, code: int = 2) -> int:
    """The one place this script picks stderr over stdout, decided by outcome not per print."""
    print(message, file=sys.stderr)
    return code


def main() -> int:
    # A settings file that is not there is this command failing, not a box with no hooks wired.
    # Printing the same line under the same exit 0 for both is the shape of false assurance this
    # whole script exists to end.
    if not settings_path().is_file():
        return fail(f"verify_hooks: no settings file at {settings_path()}, so no hook was checked")

    wired = hook_commands()
    if not wired:
        print("verify_hooks: no hooks wired in settings.json")
        return 0

    broken: list[str] = []
    unchecked: list[str] = []
    for event, command in wired:
        if event == "PARSE":
            broken.append(command)
            continue
        script = script_in(command)
        if script is None:
            unchecked.append(f"{event}: not a bare .py command, not exercised: {command[:60]}")
            continue
        bad_msg, unchecked_msg = exercise(script, event)
        if bad_msg:
            broken.append(bad_msg)
        if unchecked_msg:
            unchecked.append(unchecked_msg)

    print(f"verify_hooks: {len(wired)} wired, {len(broken)} broken, {len(unchecked)} not fully exercised")
    for b in broken:
        print(f"  BROKEN    {b}")
    for u in unchecked:
        print(f"  unchecked {u}")
    if broken:
        print("\nThese fail open, so nothing else will tell you. Fix before relying on them again.")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
