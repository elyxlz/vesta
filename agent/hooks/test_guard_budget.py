#!/usr/bin/env python3
"""Exit-code tests for guard-budget.py. Run: python3 agent/hooks/test_guard_budget.py

The hook's contract IS its exit code (0 allows, 2 denies), so every case runs it as a real
subprocess against a synthetic log rather than importing it.
"""

import json
import pathlib as pl
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

HOOK = pl.Path(__file__).resolve().parent / "guard-budget.py"

WARNING = "\x1b[33m{when} [WARNING] [SYSTEM] [RUNTIME] Rate limit allowed_warning (utilization={util}, type=seven_day)\x1b[0m"
# The agent's own logged prose quotes the same pattern; a substring match would read it as live.
PROSE = "\x1b[95m{when} [AGENT] [ASSISTANT] - saw `Rate limit allowed_warning (utilization={util}, type=seven_day)` earlier\x1b[0m"


def write_log(template: str, util: float, age_minutes: int, tmp: pl.Path) -> pl.Path:
    when = (datetime.now() - timedelta(minutes=age_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    path = pl.Path(tempfile.mkstemp(dir=tmp, suffix=".log")[1])
    path.write_text(template.format(when=when, util=util) + "\n")
    return path


def run_hook(tool: str, command: str, log_path: pl.Path | str, tmp: pl.Path) -> int:
    """Run a copy of the hook whose LOG constant points at the synthetic log."""
    src = HOOK.read_text().replace('LOG = "/root/agent/logs/vesta.log"', f'LOG = "{log_path}"')
    copy = pl.Path(tempfile.mkstemp(dir=tmp, suffix=".py")[1])
    copy.write_text(src)
    payload = json.dumps({"tool_name": tool, "tool_input": {"command": command}})
    return subprocess.run([sys.executable, str(copy)], input=payload, capture_output=True, text=True, check=False).returncode


CASES = [
    ("recent 0.99, plain bash", WARNING, "Bash", "ls -la", 0.99, 2, 2),
    ("recent 0.99, whatsapp send", WARNING, "Bash", "whatsapp send --to '+10000000000' --message x", 0.99, 2, 0),
    ("recent 0.99, app-chat send", WARNING, "Bash", "app-chat send --message hi", 0.99, 2, 0),
    ("recent 0.99, subagent", WARNING, "Agent", "", 0.99, 2, 2),
    ("recent 0.80, under ceiling", WARNING, "Bash", "ls -la", 0.80, 2, 0),
    ("stale 0.99 (3h old)", WARNING, "Bash", "ls -la", 0.99, 180, 0),
    ("recent 0.95 exactly, at ceiling", WARNING, "Bash", "ls -la", 0.95, 2, 2),
    ("non-bash tool (Read)", WARNING, "Read", "", 0.99, 2, 0),
    ("0.99 quoted in agent prose only", PROSE, "Bash", "ls -la", 0.99, 2, 0),
]


def main() -> int:
    bad = 0
    with tempfile.TemporaryDirectory() as raw:
        tmp = pl.Path(raw)
        for name, template, tool, command, util, age, want in CASES:
            log_path = write_log(template, util, age, tmp)
            code = run_hook(tool, command, log_path, tmp)
            bad += code != want
            print(f"  [{'PASS' if code == want else 'FAIL'}] {name:34} exit={code} want={want}")

        # A missing log must never block: no reading is not a high reading.
        code = run_hook("Bash", "ls", tmp / "no-such-file.log", tmp)
        bad += code != 0
        print(f"  [{'PASS' if code == 0 else 'FAIL'}] {'missing log file':34} exit={code} want=0")

    print(f"\n{bad} failure(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
