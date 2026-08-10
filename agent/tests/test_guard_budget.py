#!/usr/bin/env python3
"""Exit-code tests for agent/hooks/guard-budget.py.

The hook's contract IS its exit code (0 allows, 2 denies), so every case runs it as a real
subprocess against synthetic inputs rather than importing it.

It lives here rather than beside the hook because pytest.ini sets `testpaths = tests`, so a suite
under agent/hooks/ is never collected and its silence reads exactly like a pass. tests/ is also
dev-only, kept out of the image and the snapshot, which is where a test file belongs.
"""

import json
import pathlib as pl
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta

HOOK = pl.Path(__file__).resolve().parents[1] / "hooks/guard-budget.py"

WARNING = "\x1b[33m{when} [WARNING] [SYSTEM] [RUNTIME] Rate limit allowed_warning (utilization={util}, type=seven_day)\x1b[0m"
# The agent's own logged prose quotes the same pattern; a substring match would read it as live.
PROSE = "\x1b[95m{when} [AGENT] [ASSISTANT] - saw `Rate limit allowed_warning (utilization={util}, type=seven_day)` earlier\x1b[0m"


def write_log(template: str, util: float, age_minutes: int, tmp: pl.Path) -> pl.Path:
    when = (datetime.now() - timedelta(minutes=age_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    path = pl.Path(tempfile.mkstemp(dir=tmp, suffix=".log")[1])
    path.write_text(template.format(when=when, util=util) + "\n")
    return path


def run_hook(tool: str, command: str, log_path: pl.Path | str, tmp: pl.Path, measured: str | None = None) -> int:
    """Run a copy of the hook with LOG and MEASURED pointed at synthetic files.

    MEASURED is repointed even when a case does not use it. Otherwise every log-path test would
    read the live /root/agent/data/budget-utilization.tsv and pass or fail on whatever the box
    happened to measure this hour, which is a test suite that reports on production state.
    """
    measured_path = tmp / "measured-none.tsv"
    if measured is not None:
        measured_path = pl.Path(tempfile.mkstemp(dir=tmp, suffix=".tsv")[1])
        measured_path.write_text(measured)
    src = HOOK.read_text().replace('LOG = "/root/agent/logs/vesta.log"', f'LOG = "{log_path}"')
    src = src.replace('MEASURED = "/root/agent/data/budget-utilization.tsv"', f'MEASURED = "{measured_path}"')
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

        # The measured source, which is now primary. Stamps are built relative to now so the
        # freshness window is exercised rather than hardcoded.
        def stamp(hours_ago: float) -> str:
            return (datetime.now(UTC) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")

        measured_cases = [
            ("measured fresh 97, bash", f"{stamp(0.1)}\t97\n", "Bash", "ls", 2),
            ("measured fresh 97, whatsapp", f"{stamp(0.1)}\t97\n", "Bash", "whatsapp send --to x --message y", 0),
            ("measured fresh 40, under ceiling", f"{stamp(0.1)}\t40\n", "Bash", "ls", 0),
            # Stale must mean "no reading", never "a comfortable old reading".
            ("measured STALE 97 ignored", f"{stamp(9)}\t97\n", "Bash", "ls", 0),
            ("measured garbage ignored", "not-a-date\tnonsense\n", "Bash", "ls", 0),
            ("measured empty file ignored", "", "Bash", "ls", 0),
        ]
        for name, content, tool, command, want in measured_cases:
            # Log is deliberately absent, so only the measured source can decide.
            code = run_hook(tool, command, tmp / "no-such-file.log", tmp, measured=content)
            bad += code != want
            print(f"  [{'PASS' if code == want else 'FAIL'}] {name:34} exit={code} want={want}")

        # A missing log must never block: no reading is not a high reading.
        code = run_hook("Bash", "ls", tmp / "no-such-file.log", tmp)
        bad += code != 0
        print(f"  [{'PASS' if code == 0 else 'FAIL'}] {'missing log file':34} exit={code} want=0")

    print(f"\n{bad} failure(s)")
    return 1 if bad else 0


def test_guard_budget_suite():
    """The pytest entry point. Without it the file holds no test function, so a collector walking
    this directory finds nothing here and reports success-shaped silence."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
