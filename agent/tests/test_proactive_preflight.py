"""Exercises the REAL proactive-check preflight against a live /usage stub.

Two failure classes this pins. A budget the provider does not meter is not a budget that could not
be read: core answers 200 with an empty `meters` list for every provider without per-window
metering, and 200 with an empty list plus filled `credits` for OpenRouter, so folding either into
"unknown" rations those agents on every tick forever. And a CHECK line has to reach the exit code,
which a counter incremented inside a pipeline subshell never does.
"""

import http.server
import json
import pathlib as pl
import subprocess
import threading
import typing as tp
from datetime import UTC, datetime, timedelta

from https_stub import free_port

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "agent/skills/proactive-check/scripts/preflight.sh"

CLAUDE_PAYLOAD: dict[str, tp.Any] = {
    "meters": [
        {"label": "current session", "used_pct": 23.0, "resets_at": "2026-01-01T05:00:00+00:00"},
        {"label": "current week", "used_pct": 4.0, "resets_at": "2026-01-06T05:00:00+00:00"},
    ],
    "credits": None,
}


class _UsageHandler(http.server.BaseHTTPRequestHandler):
    """Stands in for core's GET /usage."""

    status = 200
    body = "{}"

    def do_GET(self):
        payload = self.body.encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args: object, **_kwargs: object) -> None:
        pass


def _home(tmp_path, daemons: str = "") -> pl.Path:
    """A box whose restart skill lists `daemons` and whose named commands are PATH shims."""
    (tmp_path / "bin").mkdir()
    restart = tmp_path / "agent/skills/restart"
    restart.mkdir(parents=True)
    restart.joinpath("SKILL.md").write_text(f"# Restart\n\n```bash\n{daemons}\n```\n")
    _reality_check(tmp_path)
    return tmp_path


def _reality_check(home: pl.Path, body: str = "echo 'all probes green'\n", ran_hours_ago: float | None = 1.0) -> None:
    """A stub reality_check.sh, plus a run record of the given age (None writes no record)."""
    scripts = home / "agent/skills/dream/scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    scripts.joinpath("reality_check.sh").write_text(f"#!/bin/sh\n{body}")
    data = home / "agent/data"
    data.mkdir(parents=True, exist_ok=True)
    record = data / "reality-history.tsv"
    if ran_hours_ago is None:
        record.unlink(missing_ok=True)
        return
    when = datetime.now(UTC) - timedelta(hours=ran_hours_ago)
    record.write_text(f"{when.strftime('%Y-%m-%dT%H:%M:%SZ')}\t0\n")


def _shim(home: pl.Path, name: str, script: str) -> None:
    command = home / "bin" / name
    command.write_text(f"#!/bin/sh\n{script}\n")
    command.chmod(0o755)


def _run(home: pl.Path, *, port: int, body: str = "{}", status: int = 200) -> subprocess.CompletedProcess[str]:
    _UsageHandler.body = body
    _UsageHandler.status = status
    server = http.server.HTTPServer(("127.0.0.1", port), _UsageHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        env = {
            "PATH": f"{home / 'bin'}:/usr/bin:/bin",
            "HOME": str(home),
            "WS_PORT": str(port),
            "AGENT_TOKEN": "test-token",
        }
        return subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60, check=False)
    finally:
        server.shutdown()
        server.server_close()


def test_healthy_box_prints_a_normal_band_and_exits_green(tmp_path):
    # The healthy case is exercised on purpose: a check that cannot pass green is as broken as one
    # that cannot fail.
    home = _home(tmp_path, "stub daemon start\n")
    _shim(home, "stub", 'echo \'{"running": true, "port": 61000}\'')

    run = _run(home, port=free_port(), body=json.dumps(CLAUDE_PAYLOAD))

    assert run.returncode == 0, run.stdout + run.stderr
    assert "CHECK" not in run.stdout
    assert "OK    stub daemon status" in run.stdout
    assert "OK    budget: current session at 23%, resets 2026-01-01T05:00:00+00:00" in run.stdout
    assert "BAND  normal (23% used)" in run.stdout
    assert "DIVE  yes" in run.stdout
    assert "all preflight checks green" in run.stdout


def test_a_dead_daemon_reaches_the_exit_code(tmp_path):
    # The CHECK must survive the loop: a counter incremented in a pipeline subshell is discarded by
    # the time the exit code is computed, so the preflight exits 0 with a daemon down.
    home = _home(tmp_path, "stub daemon start --instance personal\n")
    _shim(home, "stub", 'echo \'{"error": "not running"}\' >&2; exit 1')

    run = _run(home, port=free_port(), body=json.dumps(CLAUDE_PAYLOAD))

    assert run.returncode == 1, run.stdout + run.stderr
    assert "CHECK stub daemon status --instance personal" in run.stdout


def test_a_provider_without_metering_gets_the_normal_band(tmp_path):
    # meters=[] with credits=null is the stock 200 for Z.AI, Kimi and OpenAI. Reading it as an
    # unreadable budget pins every one of those agents in the cheap band forever.
    home = _home(tmp_path)

    run = _run(home, port=free_port(), body=json.dumps({"meters": [], "credits": None}))

    assert run.returncode == 0, run.stdout + run.stderr
    assert "no budget to ration against" in run.stdout
    assert "BAND  normal (no budget reported)" in run.stdout


def test_credits_are_a_measured_budget_not_an_empty_one(tmp_path):
    # OpenRouter reports the budget as dollar credits and leaves meters empty, so a meters-only
    # reader calls a measured budget unknown while the answer sits in the payload it already has.
    home = _home(tmp_path)

    run = _run(home, port=free_port(), body=json.dumps({"meters": [], "credits": {"used": 7.0, "limit": 10.0}}))

    assert run.returncode == 0, run.stdout + run.stderr
    assert "budget: credits, 7.00 of 10.00 spent at 70%" in run.stdout
    assert "BAND  watch (70% used)" in run.stdout
    assert "DIVE  no" in run.stdout


def test_a_credit_balance_with_no_limit_is_unmetered(tmp_path):
    home = _home(tmp_path)

    run = _run(home, port=free_port(), body=json.dumps({"meters": [], "credits": {"used": 7.0, "limit": None}}))

    assert run.returncode == 0, run.stdout + run.stderr
    assert "BAND  normal (no budget reported)" in run.stdout


def test_a_full_window_gets_the_tight_band(tmp_path):
    home = _home(tmp_path)
    payload = {"meters": [{"label": "current week", "used_pct": 91.0, "resets_at": "2026-01-06T05:00:00+00:00"}], "credits": None}

    run = _run(home, port=free_port(), body=json.dumps(payload))

    assert run.returncode == 0, run.stdout + run.stderr
    assert "BAND  tight (91% used)" in run.stdout
    assert "No research subagents at all" in run.stdout
    assert "DIVE  no" in run.stdout


def test_the_worst_window_sets_the_band(tmp_path):
    home = _home(tmp_path)
    payload = {
        "meters": [
            {"label": "current session", "used_pct": 3.0, "resets_at": "2026-01-01T05:00:00+00:00"},
            {"label": "current week", "used_pct": 84.0, "resets_at": "2026-01-06T05:00:00+00:00"},
        ],
        "credits": None,
    }

    run = _run(home, port=free_port(), body=json.dumps(payload))

    assert "BAND  tight (84% used)" in run.stdout


def test_a_high_credit_balance_beats_green_windows(tmp_path):
    # Claude with extra usage enabled reports rate windows AND a monthly spend balance, so a reader
    # that treats credits as a fallback for empty meters reads the balance out of the payload and
    # then discards it, banding normal on the session window while the monthly cap is nearly spent.
    home = _home(tmp_path)
    payload = {
        "meters": [{"label": "current session", "used_pct": 20.0, "resets_at": "2026-01-01T05:00:00+00:00"}],
        "credits": {"used": 95.0, "limit": 100.0},
    }

    run = _run(home, port=free_port(), body=json.dumps(payload))

    assert run.returncode == 0, run.stdout + run.stderr
    assert "budget: credits, 95.00 of 100.00 spent at 95%" in run.stdout
    assert "BAND  tight (95% used)" in run.stdout
    assert "BAND  normal" not in run.stdout
    assert "DIVE  no" in run.stdout


def test_a_window_worse_than_the_credit_balance_still_sets_the_band(tmp_path):
    # The other direction of the same max: whichever signal is worst wins, so a nearly spent window
    # is not softened by a monthly balance that is barely touched.
    home = _home(tmp_path)
    payload = {
        "meters": [{"label": "current session", "used_pct": 90.0, "resets_at": "2026-01-01T05:00:00+00:00"}],
        "credits": {"used": 5.0, "limit": 100.0},
    }

    run = _run(home, port=free_port(), body=json.dumps(payload))

    assert run.returncode == 0, run.stdout + run.stderr
    assert "budget: credits, 5.00 of 100.00 spent at 5%" in run.stdout
    assert "BAND  tight (90% used)" in run.stdout


def test_an_unreachable_endpoint_rations_and_goes_red(tmp_path):
    # Nothing listening on the port: the budget is unmeasurable, which is the one case that rations.
    home = _home(tmp_path)
    env_port = free_port()
    run = subprocess.run(
        ["sh", str(SCRIPT)],
        env={"PATH": f"{home / 'bin'}:/usr/bin:/bin", "HOME": str(home), "WS_PORT": str(env_port), "AGENT_TOKEN": "test-token"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert run.returncode == 1, run.stdout + run.stderr
    assert "CHECK the usage endpoint answered" in run.stdout
    assert "BAND  tight (budget unmeasurable)" in run.stdout


def test_a_garbage_payload_rations_and_goes_red(tmp_path):
    home = _home(tmp_path)

    run = _run(home, port=free_port(), body="<html>not json</html>")

    assert run.returncode == 1, run.stdout + run.stderr
    assert "the budget is unmeasurable" in run.stdout
    assert "BAND  tight (budget unmeasurable)" in run.stdout


def test_an_error_response_rations_and_goes_red(tmp_path):
    # core answers 502 {"error": ...} when the upstream fetch fails; that parses as JSON, so a
    # reader that only checks for meters calls a failed fetch an unmetered provider.
    home = _home(tmp_path)

    run = _run(home, port=free_port(), body=json.dumps({"error": "no oauth credentials"}), status=502)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "BAND  tight (budget unmeasurable)" in run.stdout


def test_a_null_used_pct_is_reported_not_read_as_zero(tmp_path):
    # used_pct is nullable in the schema, and coercing null to 0.0 prints a reassuring band off a
    # meter nobody measured.
    home = _home(tmp_path)
    payload = {"meters": [{"label": "current week", "used_pct": None, "resets_at": None}], "credits": None}

    run = _run(home, port=free_port(), body=json.dumps(payload))

    assert run.returncode == 1, run.stdout + run.stderr
    assert "current week reports no usable used_pct" in run.stdout
    assert "BAND  tight (budget unmeasurable)" in run.stdout


def test_a_start_line_with_no_status_verb_is_unchecked_not_healthy(tmp_path):
    # `<skill> start` is a different command from `<skill> daemon start` and has no status verb, so
    # rewriting it would flag a healthy daemon or start something as a side effect.
    home = _home(tmp_path, "browser start\n")

    run = _run(home, port=free_port(), body=json.dumps(CLAUDE_PAYLOAD))

    assert run.returncode == 0, run.stdout + run.stderr
    assert "UNCHK browser start" in run.stdout


def test_a_missing_restart_skill_goes_red(tmp_path):
    # No daemon is checked at all, which must never read as every daemon being fine.
    home = tmp_path
    (home / "bin").mkdir()

    run = _run(home, port=free_port(), body=json.dumps(CLAUDE_PAYLOAD))

    assert run.returncode == 1, run.stdout + run.stderr
    assert "no daemon is checked at all" in run.stdout


def test_a_recent_reality_check_leaves_the_watchdog_silent(tmp_path):
    # The dream ran last night, so the probe is fresh and this tick costs one file read.
    home = _home(tmp_path)
    _reality_check(home, ran_hours_ago=3)

    run = _run(home, port=free_port(), body=json.dumps(CLAUDE_PAYLOAD))

    assert run.returncode == 0, run.stdout + run.stderr
    assert "WATCHDOG" not in run.stdout


def test_a_stale_reality_check_is_run_from_the_tick(tmp_path):
    # The point of the whole branch: the probe that detects a missed dream is run by the dream, so
    # something that is not the dream has to be able to run it.
    home = _home(tmp_path)
    _reality_check(home, body="echo 'all probes green'\n", ran_hours_ago=40)

    run = _run(home, port=free_port(), body=json.dumps(CLAUDE_PAYLOAD))

    assert run.returncode == 0, run.stdout + run.stderr
    assert "WATCHDOG the reality check last ran 40h ago" in run.stdout
    assert "WATCHDOG the reality check ran clean (exit 0)." in run.stdout
    assert "CHECK" not in run.stdout


def test_a_stale_reality_check_that_reds_reaches_the_exit_code(tmp_path):
    home = _home(tmp_path)
    _reality_check(home, body="echo 'RED events.db missing at /nope'\nexit 1\n", ran_hours_ago=40)

    run = _run(home, port=free_port(), body=json.dumps(CLAUDE_PAYLOAD))

    assert run.returncode == 1, run.stdout + run.stderr
    assert "RED events.db missing at /nope" in run.stdout
    assert "CHECK the reality check exited 1" in run.stdout


def test_a_clean_probe_is_not_a_finding_because_a_line_starts_with_red(tmp_path):
    # The probe's own summary can open with the word RED while reporting nothing wrong, so the
    # verdict is its exit code. A text match here calls a healthy box a finding on every tick.
    home = _home(tmp_path)
    _reality_check(home, body="echo 'RED count over last runs (oldest first): 0 0 0'\n", ran_hours_ago=40)

    run = _run(home, port=free_port(), body=json.dumps(CLAUDE_PAYLOAD))

    assert run.returncode == 0, run.stdout + run.stderr
    assert "WATCHDOG the reality check ran clean (exit 0)." in run.stdout
    assert "CHECK" not in run.stdout


def test_the_watchdog_stamps_its_own_run_when_nothing_records_one(tmp_path):
    # Not every box keeps a run record. Without a stamp of its own the watchdog would re-run the
    # probe on every tick, which for a probe that walks the filesystem is not a cheap mistake.
    home = _home(tmp_path)
    _reality_check(home, ran_hours_ago=None)

    first = _run(home, port=free_port(), body=json.dumps(CLAUDE_PAYLOAD))
    second = _run(home, port=free_port(), body=json.dumps(CLAUDE_PAYLOAD))

    assert "WATCHDOG the reality check ran clean (exit 0)." in first.stdout
    assert second.returncode == 0, second.stdout + second.stderr
    assert "WATCHDOG" not in second.stdout


def test_a_missing_reality_check_script_goes_red(tmp_path):
    # The probe that catches silent failures cannot itself be allowed to go missing silently.
    home = _home(tmp_path)
    (home / "agent/skills/dream/scripts/reality_check.sh").unlink()

    run = _run(home, port=free_port(), body=json.dumps(CLAUDE_PAYLOAD))

    assert run.returncode == 1, run.stdout + run.stderr
    assert "CHECK reality_check.sh is missing" in run.stdout
