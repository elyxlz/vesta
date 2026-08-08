#!/usr/bin/env python3
"""Refuse discretionary work when the seven-day rate limit is close to rejecting.

WHAT IT DOES
Above THRESHOLD it denies Bash and subagent calls, and only those. Messaging commands are
allowlisted and pass at any utilization. Once the seven-day limit rejects, every trigger becomes a
zero-token no-op turn with no error anywhere: scheduled work fires and does nothing, dated items
pass unmentioned, and the user opens the app into silence. Reaching the user is therefore the LAST
capability that may stop working, never the first.

READING THE NUMBER
The runtime logs `Rate limit allowed_warning (utilization=0.96, type=seven_day)` on every request
once it is above its own warning threshold. A recent warning line is the current utilization, and
NO recent warning line means recent requests were under that threshold, which is the healthy case.
Hence MAX_AGE: when the seven-day window rolls, the lines stop appearing rather than reporting a
low number, so an old line describes nothing about now. Without that staleness bound the hook would
latch on the last high reading and never open again.

The pattern also appears inside the agent's own logged prose, so the match requires the runtime's
`[WARNING] [SYSTEM] [RUNTIME]` prefix and not the substring alone.

WIRING
PreToolUse, with a matcher for Bash and one for Agent, in `~/.claude/settings.json`:
  {"type": "command", "command": "python3 /root/agent/hooks/guard-budget.py"}
Exit 0 allows the call, exit 2 denies it and returns stderr to the agent.
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta

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

DENIAL = """BLOCKED: seven-day rate limit at {util:.2f}, over the {ceiling} ceiling.

Once the limit rejects, every trigger becomes a zero-token no-op turn: scheduled work fires and
does nothing, dated items pass unmentioned, and the user opens the app into silence. No error is
raised anywhere, so nothing will tell you it happened.

Still allowed: messaging the user. A send on whatsapp, app-chat or telegram passes this hook at
any utilization, because going quiet on them is the failure this exists to prevent.

What to do: if something cannot wait, say it to the user in one line NOW while you still can, and
write the rest down for when the window rolls. Do not spend the remainder on diagnostics, audits,
subagents or housekeeping."""


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

    util = current_utilization()
    if util is None or util < THRESHOLD:
        sys.exit(0)

    print(DENIAL.format(util=util, ceiling=THRESHOLD), file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
