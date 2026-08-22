#!/usr/bin/env python3
"""PreToolUse gate: refuse a state-changing command whose target id was scraped positionally.

WHY THIS EXISTS (built 11 Aug 2026).

On 10 Aug I ran this, to delete a reminder that had become obsolete:

    tasks remind delete $(tasks remind list --task X | grep -i "TICKETING WATCH" | awk '{print $2}')

`tasks remind list` prints TAB separated columns, and its first column reads `in 5h`, which contains
a space. With awk's DEFAULT whitespace splitting that is two fields, so `$2` was `5h` and `$3` was
the id. **The command deleted a reminder called "5h", which does not exist. It exited 0.**

Two reminders survived that way. One fired needlessly hours later. The other would have told me to
chase a GBP 96.40 refund that had already landed.

I never noticed, because the same command line ended with a `tasks remind` CREATE whose
`"status": "scheduled"` I did check. **I verified the output of the last command in the chain, not
the effect of the first.** I had even written `&& echo "chase cancelled"` after it, which fires on
exit status, so a no-op printed my own reassurance back at me. I built a false confirmation and
believed it.

THE CLASS, which is why this is code and not another rule. A mutation that silently does nothing is
indistinguishable from one that worked. That exact shape has now bitten four times in three days:

  * 8 Aug: three throwaway checks that returned "nothing found" because the check itself was broken
    (a `hasattr` on the wrong symbol, a fixture with the wrong key, a `grep -c` counting my own tool
    calls). Answered with `control.py`, which covers CHECKS.
  * 9 Aug: `runs_tgsend()` returned False on `cd /root && ENV=x python3 tgsend.py`, so the longform
    meter never ran and the message went out anyway. The guard agreeing and the guard never
    executing looked identical.
  * 10 Aug: this. Two zombie reminders.
  * 10 Aug: a mailbox sweep that returned zero hits because `--limit 200` truncated the window four
    days short of the dates being asked about.

`control.py` answered the half about checks. The half about ACTIONS had nothing, and rules have not
held: "verify the delete" is exactly the discipline that fails at 1am on the fourth command of a
chain.

WHAT IT FLAGS, deliberately narrow so it stays trustworthy:

    a mutating verb  +  an argument from a command substitution  +  positional scraping inside it

All three must be present. Positional scraping means `awk` with no `-F` (default whitespace
splitting) or a bare `cut -f`/`cut -c` on piped human output. If any leg is missing, it allows.

THE THREE WAYS ROUND IT, all closed on 12 Aug 2026. The first version understood exactly one
spelling of "argument from a command substitution", `$( )`, so the identical defect walked straight
through three others. Each was verified ALLOWED before the fix and BLOCKED after:

  * **backticks.** `tasks remind delete \\`... | awk '{print $2}'\\`` is the same command.
  * **xargs.** `... | awk '{print $2}' | xargs tasks remind delete` has no substitution at all,
    so the "no subs, skip" fast path allowed every one of them.
  * **a variable in between.** `id=$(... | awk '{print $2}'); tasks remind delete $id` splits into
    two segments, and neither one on its own has all three legs. This is the form I am most likely
    to actually type, because it is the tidy one.

AND THE HEREDOC STRIPPING WAS A REAL FAIL-OPEN, though not for the reason it was written down as.
The carried note said a mistyped terminator lets the stripper eat a live command. Bash disagrees:
asked directly, it treats those lines as heredoc BODY and never runs them, so the guard agreeing
with bash was correct. The real hole is `<<-`, which lets the terminator be TAB-INDENTED while the
old regex anchored it at column 0. Bash ends the heredoc there; the regex scanned on and swallowed
the live mutation two lines later. Demonstrated by running both and comparing, not by reading the
regex. Heredocs are now scanned line by line the way bash does it, and an opener with NO terminator
is left alone rather than stripped to the end of the string.

WHAT IT DOES NOT FLAG:

  - `--json` pipelines. `... --json | python3 -c ...` is the correct fix and must never be blocked.
  - `awk -F'\\t'` or `awk -F,`. An explicit separator means the field boundaries were thought about.
  - Reads. `grep`, `list`, `status`, `get`, `show` change nothing, so a wrong id is visible and free.
  - A literal id typed out. That is the safest form there is.
  - **Anyone else's table.** `kill $(ps aux | grep x | awk '{print $2}')` and its docker twin were
    denied until 14 Aug and should not have been: those columns are space-padded with no free text
    before the id, and a wrong pid fails loudly. The scrape source must be one of the agent's own
    table-printing CLIs, which is the closed set where a missed id no-ops at exit 0.

FAIL-OPEN, exactly as in the sibling guards: an unreadable payload, an unexpected shape, a missing
field, or any exception allows the call. A guard against silent no-ops must never itself become one
that silently blocks work.
"""

import contextlib
import json
import pathlib
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
# bare cut on a pipe: -f without an explicit -d is TAB, which is right, but -c is byte offsets
# and -d' ' on tabular output is the same class of guess.
CUT_POSITIONAL = re.compile(r"\bcut\s+(-c|-d['\"]? ['\"]?\s*-f)", re.IGNORECASE)

JSON_FLAG = re.compile(r"--json\b|--json-pretty\b|-o\s*json\b", re.IGNORECASE)


# A heredoc body is TEXT being written, not a command being run. Documenting the 10 Aug bug in a
# ledger row, or in this file's own test cases, must not trip the guard against committing it.
# Found the honest way: this guard blocked its own ledger entry within a minute of being wired, and
# then blocked the patch that fixes it. That is a real false-positive class, and no self-test of
# invented cases would have surfaced it.
HEREDOC_OPEN = re.compile(r"<<(-?)\s*(['\"]?)(\w+)\2")


def strip_heredocs(cmd: str) -> str:
    """Remove heredoc BODIES the way bash actually delimits them, line by line.

    Replaces a regex that anchored the terminator at column 0 and therefore disagreed with bash in
    the one direction that matters. Three rules, each of which the regex got wrong:

      * `<<-` accepts a TAB-INDENTED terminator. This is the fail-open: bash closed the heredoc at
        the indented terminator and ran what followed, while the regex kept scanning and swallowed
        a live mutation.
      * A terminator line must BE the delimiter, not merely start with it. `EOFF` does not close
        `EOF`, which is why an apparently-live command between a typo and the next terminator is
        really heredoc body. Confirmed by running it under bash and watching the command not fire.
      * An opener with no terminator anywhere is left ALONE rather than stripped to end-of-string.
        Bash calls that a syntax error, so the safe reading is "this is not a heredoc I understand",
        and the safe direction for a guard is to keep looking at the text rather than discard it.

    A purely numeric delimiter is ignored outright, so `$((1 << 2))` is arithmetic, not an opener.
    """
    lines = cmd.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        # EVERY `<<` on the line is a candidate, in order, not just the first. Found the honest way:
        # the first version took `HEREDOC_OPEN.search(...)`, and the very command written to verify
        # the fix was `echo "... (<<- tab terminator)"; python3 - <<'PY'`. The decoy `<<- tab` inside
        # the echo won, resolved to nothing, and the whole real heredoc body was then read as
        # commands, so the guard blocked its own test run. A line may carry a `<<` that is prose.
        chosen = None
        for m in HEREDOC_OPEN.finditer(line):
            if m.group(3).isdigit():
                continue
            dash, delim = m.group(1), m.group(3)
            for j in range(i + 1, len(lines)):
                candidate = lines[j].lstrip("\t") if dash else lines[j]
                if candidate.rstrip() == delim:
                    chosen = (m, j)
                    break
            if chosen:
                break
        if chosen is None:
            out.append(line)
            i += 1
            continue
        m, end = chosen
        out.append(line[: m.start()])
        i = end + 1
    return "\n".join(out)


def substitutions(cmd: str) -> list[str]:
    """Return the bodies of command substitutions: `$( ... )` AND backticks.

    Backticks were the cheapest way round the first version of this guard, and they are the same
    command with older syntax.
    """
    out, i = [], 0
    while True:
        start = cmd.find("$(", i)
        if start < 0:
            break
        depth, j = 1, start + 2
        while j < len(cmd) and depth:
            if cmd[j] == "(":
                depth += 1
            elif cmd[j] == ")":
                depth -= 1
            j += 1
        out.append(cmd[start + 2 : j - 1])
        i = j
    parts = cmd.split("`")
    if len(parts) > 2:
        out.extend(parts[k] for k in range(1, len(parts), 2))
    return out


# WHOSE TABLE WAS SCRAPED, added 14 Aug 2026 to close a real false positive found in review:
# `kill $(ps aux | grep -i vesta | awk '{print $2}')` and the docker twin were both DENIED, and
# both are fine. `ps` and `docker ps` space-pad their columns and their early fields never contain
# spaces, so default splitting is the documented idiom, and a wrong pid fails LOUDLY. Neither leg
# of the failure this file exists for is present. So the source is now checked, as a WHITELIST,
# for the reason `queue_gate` was inverted the same night: "tools whose whitespace columns are
# safe" is open-ended, while "tools that print MY OWN tab-separated tables" is closed and sits on
# disk. The floor is hardcoded so CI and a bare checkout behave like a live box.
CLI_FLOOR = [
    "tasks",
    "microsoft",
    "whatsapp",
    "telegram",
    "spotify",
    "tricount",
    "finance",
    "onedrive",
    "keeper",
    "browser",
    "discord",
    "slack",
    "zoom",
    "email-client",
    "google",
    "shop",
    "torrents",
    "home-assistant",
    "philips-hue",
    "samsung-tv",
    "vestad",
]
SKILL_DIRS = ("~/agent/skills", "~/agent/core/skills")


def agent_clis() -> set[str]:
    """Every CLI that prints this agent's own human tables: the floor plus what is installed."""
    names = set(CLI_FLOOR)
    for directory in SKILL_DIRS:
        with contextlib.suppress(OSError):
            names.update(p.name for p in pathlib.Path(directory).expanduser().iterdir() if not p.name.startswith("."))
    return names


AGENT_CLI = re.compile(r"(?:^|[|;&(]|\s)(" + "|".join(sorted(map(re.escape, agent_clis()), key=len, reverse=True)) + r")\b")


def scrapes_positionally(text: str) -> bool:
    """True if `text` pulls a field out of one of MY OWN human tables by position."""
    if JSON_FLAG.search(text) or not AGENT_CLI.search(text):
        return False
    return bool(AWK_DEFAULT_FIELD.search(text) or CUT_POSITIONAL.search(text))


# `... | xargs tasks remind delete` reaches the same end as a substitution with none of the syntax,
# so the "no substitutions, nothing to check" fast path let every one of them through.
XARGS_TAIL = re.compile(r"\|\s*xargs\b(.*)$", re.IGNORECASE | re.DOTALL)

# `id=$(...)` / ``id=`...` `` : the tidy two-statement form, which is the one I actually type.
ASSIGN_FROM_SUB = re.compile(r"(?:^|[;&|]|\s)(\w+)=(?=\$\(|`)")

# A mutating verb inside a QUOTED LITERAL is display text, not a command. Found within the hour of
# widening this guard, by the guard blocking me: `printf 'stop rc=%s %s\n' "$rc" "$(... | cut -c1-100)"`
# was denied because the word "stop" sits in a printf FORMAT STRING and the substitution truncates
# output for display. Neither half is a mutation. The 14,239-command replay had not caught this
# because it measured commands I had ALREADY written, and I had spent the same session adopting a
# new habit, `| tr -d '\n' | cut -c1-N` for compact status lines, that the history barely contains.
# A false-positive rate measured against the past does not bound the rate against how you write now.
QUOTED = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")


def command_text(seg: str) -> str:
    """The part of a segment that can actually name a command: quoted literals removed.

    Deliberately NOT applied to substitution bodies, only to the text outside them, so
    `tasks remind delete "$id"` still reads as a mutation while `printf 'stop ...'` does not.
    """
    return QUOTED.sub(" ", seg)


def scrape_feeding_mutation(seg: str, subs: list[str]) -> str | None:
    """Shape 1: the mutator sits OUTSIDE the substitution, the positional scrape INSIDE it."""
    outside = seg
    for s in subs:
        outside = outside.replace(s, " ")
    if not MUTATORS.search(command_text(outside)):
        return None
    for s in subs:
        if scrapes_positionally(s):
            return s.strip()
    return None


def record_tainted(seg: str, subs: list[str], tainted: dict[str, str]) -> None:
    """Shape 2: the scrape lands in a variable here and the mutation comes in a later segment."""
    for name in ASSIGN_FROM_SUB.findall(seg):
        for s in subs:
            if scrapes_positionally(s):
                tainted[name] = s.strip()


def tainted_spent_here(seg: str, tainted: dict[str, str]) -> str | None:
    """Shape 3: a variable filled from a scrape is now being spent on a mutation."""
    if not tainted or not MUTATORS.search(command_text(seg)):
        return None
    for name, src in tainted.items():
        if re.search(r"\$\{?" + re.escape(name) + r"\}?\b", seg):
            return src
    return None


def scrape_piped_to_mutation(seg: str) -> str | None:
    """Shape 4: `... | awk '{print $2}' | xargs <mutator>`, no substitution anywhere."""
    m = XARGS_TAIL.search(seg)
    if not m or not MUTATORS.search(command_text(m.group(1))):
        return None
    upstream = seg[: m.start()]
    return upstream.strip() if scrapes_positionally(upstream) else None


def verdict(cmd: str) -> str | None:
    """Return the offending substitution (a reason to block), or None to allow.

    The four shapes live in four named functions rather than four branches here. They are four
    distinct SPELLINGS of one defect, each found by replaying real command history, and each is
    worth naming: a denial that can say which spelling matched is actionable where a generic one
    is not. That is also why this reads as a dispatch loop instead of a nest of conditionals.

    The scraped value must plausibly FEED the mutation, so both must live in the SAME command
    segment. Replaying 12,709 real historical commands showed why: `before=$(df -h / | tail -1 |
    awk '{print $4}'); rm -rf /tmp/pytest-of-root` has a scrape and a mutator, and they have
    nothing to do with each other. The substitution measures disk for a progress message. Matching
    "mutator anywhere in the line" flagged a whole class of these.
    """
    cmd = strip_heredocs(cmd)

    # Variables that were filled from a positional scrape. Tracked across segments, because the
    # tidy `id=$(...)` / `mutate $id` form puts the scrape and the mutation in different ones and
    # neither half alone has all three legs.
    tainted: dict[str, str] = {}

    for seg in re.split(r";|&&|\|\||\n", cmd):
        subs = substitutions(seg)
        if subs:
            hit = scrape_feeding_mutation(seg, subs)
            if hit:
                return hit
            record_tainted(seg, subs, tainted)

        hit = tainted_spent_here(seg, tainted) or scrape_piped_to_mutation(seg)
        if hit:
            return hit

    return None


CASES = [
    # (must_block, label, command)
    (True, "the actual 10 Aug bug", """tasks remind delete $(tasks remind list --task X | grep -i "WATCH" | awk '{print $2}')"""),
    (True, "same shape via cut -c", """tasks done $(tasks list | grep foo | cut -c10-18)"""),
    (
        True,
        "calendar delete off a scraped column",
        """microsoft calendar delete --id $(microsoft calendar list | grep XZ | awk '{print $4}')""",
    ),
    (False, "FIX 1: --json", """tasks remind delete $(tasks remind list --json | python3 -c "import sys,json;print(1)")"""),
    (False, "FIX 2: explicit tab separator", """tasks remind delete $(tasks remind list | grep W | awk -F'\t' '{print $2}')"""),
    (False, "FIX 3: literal id", """tasks remind delete a9fa757e"""),
    (False, "read-only scrape changes nothing", """tasks remind list | grep -i olbia | awk '{print $2}'"""),
    (False, "no substitution at all", """rm /tmp/scratch.txt"""),
    (False, "mutating word only INSIDE the substitution", """echo $(tasks list | awk '{print $2}')"""),
    # Found LIVE, not invented: this guard blocked its own ledger row, because the row documents
    # the bad command. Then it blocked the patch fixing that. Writing about a mistake is not making
    # it, and a guard that cannot tell those apart makes its own lessons unrecordable.
    (
        False,
        "the bad command quoted inside a heredoc is text, not execution",
        (
            "cat >> /root/agent/dreamer/ledger.md <<'ENTRY'\n"
            "tasks remind delete $(tasks remind list | grep W | awk '{print $2}') deleted nothing\n"
            "ENTRY"
        ),
    ),
    (
        True,
        "a real mutation AFTER a heredoc still blocks",
        (
            "cat > /tmp/x <<'EOF'\nharmless text\nEOF\n"
            """tasks remind delete $(tasks remind list | grep W | awk '{print $2}')"""
        ),
    ),
    # ---- the four ways round the first version, closed 12 Aug. Each was verified ALLOWED before
    # the fix. The negative twin under each one is what stops the new rule being a blunt instrument.
    (True, "GAP 1: backticks instead of $( )", """tasks remind delete `tasks remind list --task X | grep WATCH | awk '{print $2}'`"""),
    (False, "  twin: backticks on a READ change nothing", """echo `tasks remind list | awk '{print $2}'`"""),
    (
        True,
        "GAP 2: xargs, no substitution anywhere",
        """tasks remind list --task X | grep WATCH | awk '{print $2}' | xargs tasks remind delete""",
    ),
    (False, "  twin: xargs with NO positional scrape is the normal safe idiom", """find /tmp -name '*.log' -mtime +7 | xargs rm -f"""),
    (False, "  twin: xargs fed from --json output", """tasks list --json | jq -r '.[].id' | xargs -n1 tasks done"""),
    (
        True,
        "GAP 3: the scrape parks in a variable, the mutation spends it",
        """id=$(tasks remind list --task X | grep WATCH | awk '{print $2}'); tasks remind delete $id""",
    ),
    (
        True,
        "GAP 3b: same, separated by a newline and braced",
        "rid=$(tasks remind list | grep WATCH | awk '{print $2}')\ntasks remind delete ${rid}",
    ),
    (
        False,
        "  twin: a scraped variable the mutation never touches (12,709-command replay case)",
        """before=$(df -h / | tail -1 | awk '{print $4}'); rm -rf /tmp/pytest-of-root""",
    ),
    (
        False,
        "  twin: variable scraped with an explicit separator",
        """id=$(tasks remind list | grep W | awk -F'\t' '{print $2}'); tasks remind delete $id""",
    ),
    # GAP 4 was carried as "a mistyped terminator lets the stripper eat a live command". Bash says
    # otherwise: those lines are heredoc BODY and never run. The real hole is `<<-`, whose
    # terminator may be TAB-INDENTED while the old regex demanded column 0, so bash ended the
    # heredoc and ran the mutation while the guard was still swallowing text.
    (
        True,
        "GAP 4: <<- with a tab-indented terminator, mutation after it is LIVE",
        (
            "cat > /tmp/a <<-'EOF'\n\talpha\n\tEOF\n"
            """tasks remind delete $(tasks remind list | awk '{print $2}')"""
        ),
    ),
    (
        False,
        "  twin: a mistyped terminator really IS body, bash never runs it",
        "cat > /tmp/a <<'EOF'\nalpha\nEOFF\ntasks remind delete $(tasks remind list | awk '{print $2}')\nEOF",
    ),
    (False, "  twin: arithmetic shift is not a heredoc opener", """test $((1 << 2)) -eq 4 && rm -f /tmp/scratch"""),
    # FOUND BY THE GUARD BLOCKING ME, 12 Aug 05:12, about an hour after the rules above shipped.
    # The mutating word lives in a printf FORMAT STRING and the substitution truncates output for
    # display. Neither half is a mutation, and the 14,239-command replay had missed the whole class
    # because I adopted the `| tr -d '\n' | cut -c1-N` status-line habit in the same session.
    (
        False,
        "  twin: a mutating word inside a printf format string is display text",
        """out=$(whatsapp daemon stop 2>&1); printf 'stop rc=%s %s\\n' "$rc" "$(printf '%s' "$out" | tr -d '\\n' | cut -c1-100)\"""",
    ),
    (
        False,
        "  twin: 'delete' quoted in an echo, with a truncating substitution alongside",
        """echo "nothing to delete here"; echo "$(ls -l /tmp | cut -c1-40)\"""",
    ),
    (
        True,
        "  and the real thing still blocks when the verb is UNQUOTED",
        """tasks remind delete "$(tasks remind list | grep W | awk '{print $2}')\"""",
    ),
    # FOUND IN REVIEW, 11 Aug, and both of these were denied until 14 Aug. `ps` and `docker ps`
    # space-pad their columns and their early fields never contain spaces, so default splitting is
    # the documented idiom; a wrong pid or container id also fails LOUDLY. Neither leg of the
    # failure this guard exists for is present, so both must be allowed.
    (False, "REVIEW: ps aux columns are whitespace-safe, kill fails loudly", """kill $(ps aux | grep -i vesta | awk '{print $2}')"""),
    (False, "  twin: docker ps, same idiom", """docker stop $(docker ps | grep vesta | awk '{print $1}')"""),
    # The control in the other direction, and the reason the fix is a whitelist rather than a
    # carve-out: the identical pipeline shape over one of MY tables must still block.
    (True, "  control: the same shape over my own table still blocks", """tasks done $(tasks list | grep vesta | awk '{print $2}')"""),
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


# Emitted as the STRUCTURED decision its siblings use, not a bare exit 2. Both block in practice,
# but `verify_hooks.py` reads `hookSpecificOutput.permissionDecision` from stdout, so a stderr-only
# guard is unverifiable by my own nightly checker: it reported this one BROKEN, "no parseable hook
# decision at all", minutes after it had demonstrably blocked four real commands. A guard my
# instruments cannot read is a guard I cannot trust later.
DENIAL = (
    "blind mutation: this changes state using an id scraped positionally from a human "
    "table, and if the scrape is wrong the command will do NOTHING and still exit 0.\n\n"
    "  the substitution: {bad}\n\n"
    "on 10 Aug this exact shape deleted a reminder called '5h', because `tasks remind list` "
    "prints tab-separated columns whose first field is 'in 5h' and awk's default splitting "
    "made $2 the duration, not the id. two reminders survived and one fired hours later.\n\n"
    "do one of these instead:\n"
    "  1. use the tool's --json output and parse it (tasks/tasks remind both support it)\n"
    "  2. pass -F'\\t' to awk so the field boundaries are explicit\n"
    "  3. paste the id literally\n"
    "and then RE-QUERY to confirm the thing is actually gone. checking the command's own "
    "exit status proves nothing here: a no-op exits 0."
)


def offending_substitution(payload: object) -> str | None:
    """The substitution worth denying in this hook payload, or None if there is nothing to deny."""
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    cmd = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(cmd, str) or not cmd:
        return None
    return verdict(cmd)


def deny_if_blind(payload: object) -> None:
    """Print the structured denial, or nothing at all if this payload is fine."""
    bad = offending_substitution(payload)
    if not bad:
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": DENIAL.format(bad=bad[:160]),
                }
            }
        )
    )


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    # One fail-open suppression around the whole path, which is the documented intent: a guard that
    # can crash the tool call it guards is worse than the mistake it prevents.
    with contextlib.suppress(Exception):
        deny_if_blind(json.load(sys.stdin))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
