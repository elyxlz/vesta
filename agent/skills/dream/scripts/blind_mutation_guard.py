#!/usr/bin/env python3
"""PreToolUse gate: refuse a state-changing command whose target id was scraped positionally.

THE SHAPE, in one line:

    tool delete $(tool list | grep <thing> | awk '{print $2}')

`awk` with no `-F` splits on runs of whitespace, so the field numbers only line up while every
column is a single word. A human-readable table breaks that promise routinely: a column reading
`in 5h` is two fields, everything after it shifts by one, and `$2` hands back the duration instead
of the id. The delete then names a row that does not exist.

Which is the reason this is a guard and not a rule. A mutation that silently does nothing is
indistinguishable from one that worked: the command exits 0, an `&& echo "done"` chained after it
prints on that exit status, and the reassurance is manufactured by the very thing that failed. If
the same command line ends with another call whose output IS checked, the check reads as coverage
for the whole chain. Nothing surfaces until the state that should have changed acts on its own.

WHAT IT FLAGS, deliberately narrow so it stays trustworthy:

    a mutating verb  +  an argument from a command substitution  +  positional scraping inside it

All three must be present. Positional scraping means `awk` with no `-F` (default whitespace
splitting) or a bare `cut -f`/`cut -c` over piped human output. If any leg is missing, it allows.

WHAT IT DOES NOT FLAG:

  - `--json` pipelines. `... --json | python3 -c ...` is the correct fix and must never be blocked.
  - `awk -F'\\t'` or `awk -F,`. An explicit separator means the field boundaries were thought about.
  - Reads. `grep`, `list`, `status`, `get`, `show` change nothing, so a wrong id is visible and free.
  - A literal id typed out. That is the safest form there is.

FAIL-OPEN: an unreadable payload, an unexpected shape, a missing field, or any exception allows the
call. A guard against silent no-ops must never itself become one that silently blocks work.

Usage: wired as a PreToolUse hook on `Bash` (see the dream SKILL.md); `--self-test` runs its cases.
"""

import json
import re
import sys

# Verbs that change durable state. A wrong id here fails silently and expensively.
MUTATORS = re.compile(
    r"\b(delete|remove|rm|postpone|snooze|update|move|archive|done|complete|close|cancel|revoke|"
    r"disable|scrub|redact|kill|stop|drop|purge|reset)\b",
    re.IGNORECASE,
)

# awk with NO -F: default whitespace splitting, which is the actual bug.
AWK_DEFAULT_FIELD = re.compile(r"\bawk\s+(?!-F)(?:[^|)]*?)'\s*\{\s*print\s+\$\d+", re.IGNORECASE)
# A bare cut on a pipe. `-f` without `-d` is TAB, which is right; `-c` is byte offsets and `-d' '`
# over tabular output is the same guess about where the columns are.
CUT_POSITIONAL = re.compile(r"\bcut\s+(-c|-d['\"]? ['\"]?\s*-f)", re.IGNORECASE)

JSON_FLAG = re.compile(r"--json\b|--json-pretty\b|-o\s*json\b", re.IGNORECASE)

# A heredoc body is TEXT being written, not a command being run. Recording one of these mistakes in
# a note, or in this file's own cases, is not making it, and a guard that cannot tell those apart
# makes its own lessons unrecordable.
HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?\n.*?^\1\b", re.DOTALL | re.MULTILINE)


def strip_heredocs(cmd: str) -> str:
    return HEREDOC.sub(" ", cmd)


def substitutions(cmd: str) -> list[str]:
    """Return the bodies of $( ... ) substitutions, handling one level of nesting."""
    out, i = [], 0
    while True:
        start = cmd.find("$(", i)
        if start < 0:
            return out
        depth, j = 1, start + 2
        while j < len(cmd) and depth:
            if cmd[j] == "(":
                depth += 1
            elif cmd[j] == ")":
                depth -= 1
            j += 1
        out.append(cmd[start + 2 : j - 1])
        i = j


def verdict(cmd: str) -> str | None:
    """Return the offending substitution, or None to allow.

    The scraped value must plausibly FEED the mutation, so both have to live in the same command
    segment. `before=$(df -h / | tail -1 | awk '{print $4}'); rm -rf /tmp/build` carries a scrape
    and a mutator that have nothing to do with each other: the substitution measures disk for a
    progress line. Matching a mutator anywhere on the line flags that whole class.
    """
    cmd = strip_heredocs(cmd)
    for seg in re.split(r";|&&|\|\||\n", cmd):
        subs = substitutions(seg)
        if not subs:
            continue
        outside = seg
        for s in subs:
            outside = outside.replace(s, " ")
        if not MUTATORS.search(outside):
            continue
        for s in subs:
            if JSON_FLAG.search(s):
                continue
            if AWK_DEFAULT_FIELD.search(s) or CUT_POSITIONAL.search(s):
                return s.strip()
    return None


REASON = (
    "blind mutation: this changes state using an id scraped positionally from a human-readable "
    "table, and if the scrape is wrong the command will do NOTHING and still exit 0.\n\n"
    "  the substitution: {sub}\n\n"
    "`awk` with no -F splits on whitespace, so a column whose value contains a space (a duration "
    "like `in 5h`, a two-word status, a name) shifts every field after it and $2 stops being the "
    "id. The delete then names a row that does not exist and reports success.\n\n"
    "do one of these instead:\n"
    "  1. use the tool's --json output and parse it\n"
    "  2. pass -F'\\t' to awk so the field boundaries are explicit\n"
    "  3. paste the id literally\n"
    "and then RE-QUERY to confirm the thing is actually gone. Checking the command's own exit "
    "status proves nothing here: a no-op exits 0."
)

CASES = [
    # (must_block, label, command)
    (
        True,
        "id scraped out of a tab-separated listing",
        """tasks remind delete $(tasks remind list --task X | grep -i "WATCH" | awk '{print $2}')""",
    ),
    (True, "same shape via cut -c", """tasks done $(tasks list | grep foo | cut -c10-18)"""),
    (
        True,
        "calendar delete off a scraped column",
        """microsoft calendar delete --id $(microsoft calendar list | grep XZ | awk '{print $4}')""",
    ),
    (False, "FIX 1: --json", """tasks remind delete $(tasks remind list --json | python3 -c "import sys,json;print(1)")"""),
    (False, "FIX 2: explicit tab separator", """tasks remind delete $(tasks remind list | grep W | awk -F'\t' '{print $2}')"""),
    (False, "FIX 3: literal id", """tasks remind delete a9fa757e"""),
    (False, "read-only scrape changes nothing", """tasks remind list | grep -i sail | awk '{print $2}'"""),
    (False, "no substitution at all", """rm /tmp/scratch.txt"""),
    (False, "mutating word only INSIDE the substitution", """echo $(tasks list | awk '{print $2}')"""),
    (
        False,
        "the bad command quoted inside a heredoc is text, not execution",
        ("cat >> ~/agent/data/notes.md <<'ENTRY'\ntasks remind delete $(tasks remind list | grep W | awk '{print $2}') deleted nothing\nENTRY"),
    ),
    (
        True,
        "a real mutation AFTER a heredoc still blocks",
        (
            "cat > /tmp/x <<'EOF'\nharmless text\nEOF\n"
            """tasks remind delete $(tasks remind list | grep W | awk '{print $2}')"""
        ),
    ),
]


def self_test() -> int:
    """Controls in BOTH directions. A guard that cannot show itself firing on the known-bad case
    and staying silent on the three correct fixes is not evidence of anything."""
    fails = []
    for want, label, cmd in CASES:
        got = verdict(cmd) is not None
        if got != want:
            fails.append(f"{'MISSED' if want else 'FALSE POSITIVE'}: {label}")
    for f in fails:
        print("  SELF-TEST:", f)
    print(
        f"blind_mutation_guard: {'self-test clean' if not fails else 'SELF-TEST FAILED'} "
        f"({len(CASES)} cases, {sum(1 for c in CASES if c[0])} must block)"
    )
    return 1 if fails else 0


def offending_substitution(payload: object) -> str | None:
    """The substitution to refuse in one hook payload, or None to allow. Every shape that is not a
    Bash call carrying a command string reads as nothing to refuse, which is the fail-open half."""
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    cmd = tool_input.get("command") if isinstance(tool_input, dict) else None
    return verdict(cmd) if isinstance(cmd, str) and cmd else None


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    try:
        bad = offending_substitution(json.load(sys.stdin))
    except Exception:
        return 0
    # The STRUCTURED decision, not a bare exit 2. Both block in practice, but `verify_hooks.py`
    # reads `hookSpecificOutput.permissionDecision` from stdout, so a stderr-only guard reports as
    # having no parseable verdict at all and can never be shown to still have teeth.
    if bad:
        decision = {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": REASON.format(sub=bad[:160])}
        print(json.dumps({"hookSpecificOutput": decision}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
