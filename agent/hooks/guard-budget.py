#!/usr/bin/env python3
"""Refuse discretionary work when the budget is close to refusing turns outright.

WHAT IT DOES
Above THRESHOLD it denies Bash and subagent calls, and only those. Messaging commands are
allowlisted and pass at any utilization. Once a limit rejects, every trigger becomes a zero-token
no-op turn with no error anywhere: scheduled work fires and does nothing, dated items pass
unmentioned, and the user opens the app into silence. Reaching the user is therefore the LAST
capability that may stop working, never the first.

READING THE NUMBER
Primary source is `MEASURED`, the file the proactive tick's preflight publishes: the provider's own
usage endpoint, every rate window and the credit balance folded into one worst-case percentage. A
file older than MEASURED_MAX_AGE counts as no reading rather than a low one, so a tick that stopped
running cannot license spending.

Fallback is the runtime's `Rate limit allowed_warning (utilization=0.96, type=seven_day)` lines. It
is a fallback because it is an inference, not a measurement: those lines appear only while the
runtime is already warning, they name one window, and a monthly spend cap never appears in them.
Hence MAX_AGE: when the window rolls, the lines stop appearing rather than reporting a low number,
so an old line describes nothing about now, and without that bound the hook would latch on the last
high reading and never open again.

The pattern also appears inside the agent's own logged prose, so the match requires the runtime's
`[WARNING] [SYSTEM] [RUNTIME]` prefix and not the substring alone.

Both sources may be missing, and that keeps meaning "no reading, so allow": failing open is
deliberate, because a hook that blocks when it cannot see bricks the box the moment its input goes
missing.

WIRING
PreToolUse, with a matcher for Bash and one for Agent, in `~/.claude/settings.json`:
  {"type": "command", "command": "python3 /root/agent/hooks/guard-budget.py"}
Exit 0 allows the call, exit 2 denies it and returns stderr to the agent.
"""

import json
import pathlib as pl
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta

THRESHOLD = 0.95
MAX_AGE = timedelta(minutes=45)
LOG = "/root/agent/logs/vesta.log"
TAIL_LINES = "4000"

# Reaching the user never gets blocked, whatever the number says.
ALLOW = re.compile(r"\b(whatsapp|app-chat|telegram)\b[^|;&]*\b(send|react|list-messages|history|messages)\b")

ANSI = re.compile(r"\x1b\[[0-9;]*m")
LINE = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[WARNING\] \[SYSTEM\] \[RUNTIME\] "
    r"Rate limit allowed_warning \(utilization=([0-9.]+), type=seven_day\)"
)

DENIAL = """BLOCKED: budget utilization at {util:.2f}, over the {ceiling} ceiling.

Once the limit rejects, every trigger becomes a zero-token no-op turn: scheduled work fires and
does nothing, dated items pass unmentioned, and the user opens the app into silence. No error is
raised anywhere, so nothing will tell you it happened.

Still allowed: messaging the user. A send on whatsapp, app-chat or telegram passes this hook at
any utilization, because going quiet on them is the failure this exists to prevent.

What to do: if something cannot wait, say it to the user in one line NOW while you still can, and
write the rest down for when the window rolls. Do not spend the remainder on diagnostics, audits,
subagents or housekeeping."""


MEASURED = "/root/agent/data/budget-utilization.tsv"
MEASURED_MAX_AGE = timedelta(hours=2)


def measured_utilization(path: str = MEASURED) -> float | None:
    """The hourly proactive tick's own measurement, which is the authoritative source.

    The log path below infers the number from residue rather than measuring it. `allowed_warning`
    lines exist only while the runtime is already warning, they name `type=seven_day` alone, and a
    monthly spend cap never appears in them at all, so a hook reading only those can be blind to the
    limit that actually stops the box.

    preflight.sh asks the provider's usage endpoint every tick and folds every rate window AND the
    credit balance into one worst-case percentage. Reading what it publishes is a measurement, and
    it costs one small file read per tool call instead of an HTTP request. Returns 0..1 to match the
    log path's scale.
    """
    try:
        stamp, value = pl.Path(path).read_text().strip().split("\t")[:2]
        when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None
    # A stale file is silence, not a low reading. If the tick stopped running, this must not report
    # a comfortable old number and license spending; fall through to the log and then to fail-open.
    if datetime.now(UTC).replace(tzinfo=None) - when > MEASURED_MAX_AGE:
        return None
    try:
        return float(value) / 100.0
    except ValueError:
        return None


def current_utilization(log_path: str = LOG) -> float | None:
    """Newest seven-day warning in the log, if it is recent enough to describe now."""
    try:
        tail = subprocess.run(["tail", "-n", TAIL_LINES, log_path], capture_output=True, text=True, timeout=10, check=False).stdout
    except Exception:
        return None
    newest = None
    for raw in tail.splitlines():
        match = LINE.search(ANSI.sub("", raw))
        if match:
            newest = match
    if not newest:
        return None
    try:
        when = datetime.strptime(newest.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    # Stale: warnings stop appearing entirely once the window rolls, so an old one says nothing.
    if datetime.now() - when > MAX_AGE:
        return None
    return float(newest.group(2))


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if payload.get("tool_name", "") not in ("Bash", "Agent", "Task"):
        sys.exit(0)

    command = str(payload.get("tool_input", {}).get("command", ""))
    if ALLOW.search(command):
        sys.exit(0)

    # Measurement first, log residue only as a fallback, and None from both means no reading.
    util = measured_utilization()
    if util is None:
        util = current_utilization()
    if util is None or util < THRESHOLD:
        sys.exit(0)

    print(DENIAL.format(util=util, ceiling=THRESHOLD), file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
