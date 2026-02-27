import json
import os
import signal
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta, UTC
from pathlib import Path

import pytest

CLI_DIR = Path(__file__).parent.parent
REMINDER_BIN = str(CLI_DIR / ".venv" / "bin" / "reminder")


def reminder_cli(state_dir: Path, *args: str, timeout: float = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        [REMINDER_BIN, "--state-dir", str(state_dir), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def start_daemon(state_dir: Path) -> subprocess.Popen:
    proc = subprocess.Popen(
        [REMINDER_BIN, "--state-dir", str(state_dir), "serve"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env={**os.environ, "REMINDER_SYNC_INTERVAL": "1"},
    )
    line = proc.stdout.readline()
    assert "serving" in line, f"daemon failed to start: {line}"
    return proc


def stop_daemon(proc: subprocess.Popen):
    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="session")
def shared_env(tmp_path_factory):
    state_dir = tmp_path_factory.mktemp("shared")
    (state_dir / "data" / "reminder").mkdir(parents=True)
    (state_dir / "logs" / "reminder").mkdir(parents=True)
    (state_dir / "notifications").mkdir(parents=True)

    proc = start_daemon(state_dir)
    yield state_dir, proc
    stop_daemon(proc)


def parse(result: subprocess.CompletedProcess):
    output = result.stdout.strip()
    if not output:
        output = result.stderr.strip()
    return json.loads(output)


# --- Basic CRUD (shared daemon) ---

class TestSetReminder:
    def test_set_with_in_minutes(self, shared_env):
        state_dir, _ = shared_env
        data = parse(reminder_cli(state_dir, "set", "take a break", "--in-minutes", "30"))
        assert data["status"] == "scheduled"
        assert "30 minutes" in data["schedule"]

    def test_set_with_in_hours(self, shared_env):
        state_dir, _ = shared_env
        data = parse(reminder_cli(state_dir, "set", "--message", "lunch", "--in-hours", "2"))
        assert "2 hours" in data["schedule"]

    def test_set_with_in_days(self, shared_env):
        state_dir, _ = shared_env
        data = parse(reminder_cli(state_dir, "set", "weekly review", "--in-days", "7"))
        assert "7 days" in data["schedule"]

    def test_set_combined_units(self, shared_env):
        state_dir, _ = shared_env
        data = parse(reminder_cli(state_dir, "set", "meeting", "--in-hours", "1", "--in-minutes", "30"))
        assert "hour" in data["schedule"]
        assert "minute" in data["schedule"]

    def test_set_with_datetime_and_tz(self, shared_env):
        state_dir, _ = shared_env
        future = (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
        data = parse(reminder_cli(state_dir, "set", "event", "--scheduled-datetime", future, "--tz", "UTC"))
        assert data["status"] == "scheduled"
        assert "once at" in data["schedule"]

    def test_set_requires_message(self, shared_env):
        state_dir, _ = shared_env
        r = reminder_cli(state_dir, "set", "--in-minutes", "5")
        assert r.returncode != 0
        assert "message" in parse(r)["error"].lower()

    def test_set_requires_time(self, shared_env):
        state_dir, _ = shared_env
        r = reminder_cli(state_dir, "set", "no time")
        assert r.returncode != 0

    def test_set_requires_tz_with_datetime(self, shared_env):
        state_dir, _ = shared_env
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        r = reminder_cli(state_dir, "set", "test", "--scheduled-datetime", future)
        assert r.returncode != 0
        assert "tz" in parse(r)["error"].lower()

    def test_set_rejects_negative_minutes(self, shared_env):
        state_dir, _ = shared_env
        r = reminder_cli(state_dir, "set", "bad", "--in-minutes", "-5")
        assert r.returncode != 0

    def test_set_invalid_timezone(self, shared_env):
        state_dir, _ = shared_env
        r = reminder_cli(state_dir, "set", "test", "--scheduled-datetime", "2025-06-15T10:00:00", "--tz", "Fake/Zone")
        assert r.returncode != 0
        assert "timezone" in parse(r)["error"].lower()


class TestSetRecurring:
    def test_hourly(self, shared_env):
        state_dir, _ = shared_env
        data = parse(reminder_cli(state_dir, "set", "check msgs", "--recurring", "hourly"))
        assert data["schedule"] == "hourly"

    def test_daily(self, shared_env):
        state_dir, _ = shared_env
        data = parse(reminder_cli(state_dir, "set", "standup", "--recurring", "daily", "--scheduled-datetime", "2024-12-02T10:30:00", "--tz", "UTC"))
        assert "daily" in data["schedule"]
        assert "10:30" in data["schedule"]

    def test_weekly(self, shared_env):
        state_dir, _ = shared_env
        data = parse(reminder_cli(state_dir, "set", "review", "--recurring", "weekly", "--scheduled-datetime", "2024-12-06T17:00:00", "--tz", "UTC"))
        assert "weekly" in data["schedule"]
        assert "fri" in data["schedule"]

    def test_monthly(self, shared_env):
        state_dir, _ = shared_env
        data = parse(reminder_cli(state_dir, "set", "bills", "--recurring", "monthly", "--scheduled-datetime", "2024-12-15T09:00:00", "--tz", "UTC"))
        assert "monthly" in data["schedule"]
        assert "day 15" in data["schedule"]

    def test_yearly(self, shared_env):
        state_dir, _ = shared_env
        data = parse(reminder_cli(state_dir, "set", "birthday", "--recurring", "yearly", "--scheduled-datetime", "2024-03-14T12:00:00", "--tz", "UTC"))
        assert "yearly" in data["schedule"]

    def test_daily_requires_datetime(self, shared_env):
        state_dir, _ = shared_env
        r = reminder_cli(state_dir, "set", "test", "--recurring", "daily")
        assert r.returncode != 0


class TestListReminders:
    def test_list_returns_items(self, shared_env):
        state_dir, _ = shared_env
        r = reminder_cli(state_dir, "list")
        items = parse(r)
        assert isinstance(items, list)
        assert len(items) >= 1

    def test_list_respects_limit(self, shared_env):
        state_dir, _ = shared_env
        r = reminder_cli(state_dir, "list", "--limit", "2")
        assert len(parse(r)) <= 2

    def test_list_has_next_run(self, shared_env):
        state_dir, _ = shared_env
        items = parse(reminder_cli(state_dir, "list"))
        has_next_run = any(i["next_run"] is not None for i in items)
        assert has_next_run


class TestUpdateReminder:
    def test_update_message(self, shared_env):
        state_dir, _ = shared_env
        s = parse(reminder_cli(state_dir, "set", "to update", "--in-minutes", "60"))
        data = parse(reminder_cli(state_dir, "update", s["id"], "--message", "updated"))
        assert data["message"] == "updated"
        assert data["status"] == "updated"

    def test_update_via_flag(self, shared_env):
        state_dir, _ = shared_env
        s = parse(reminder_cli(state_dir, "set", "old", "--in-minutes", "60"))
        data = parse(reminder_cli(state_dir, "update", "--id", s["id"], "--message", "new"))
        assert data["status"] == "updated"

    def test_update_nonexistent(self, shared_env):
        state_dir, _ = shared_env
        r = reminder_cli(state_dir, "update", "nope", "--message", "x")
        assert r.returncode != 0

    def test_update_requires_id(self, shared_env):
        state_dir, _ = shared_env
        r = reminder_cli(state_dir, "update", "--message", "x")
        assert r.returncode != 0


class TestCancelReminder:
    def test_cancel(self, shared_env):
        state_dir, _ = shared_env
        s = parse(reminder_cli(state_dir, "set", "bye", "--in-minutes", "60"))
        data = parse(reminder_cli(state_dir, "cancel", s["id"]))
        assert data["status"] == "cancelled"

    def test_cancel_via_flag(self, shared_env):
        state_dir, _ = shared_env
        s = parse(reminder_cli(state_dir, "set", "bye2", "--in-minutes", "60"))
        data = parse(reminder_cli(state_dir, "cancel", "--id", s["id"]))
        assert data["status"] == "cancelled"

    def test_cancel_removes_from_list(self, shared_env):
        state_dir, _ = shared_env
        s = parse(reminder_cli(state_dir, "set", "bye3", "--in-minutes", "60"))
        reminder_cli(state_dir, "cancel", s["id"])
        items = parse(reminder_cli(state_dir, "list"))
        assert not any(i["id"] == s["id"] for i in items)

    def test_cancel_nonexistent(self, shared_env):
        state_dir, _ = shared_env
        r = reminder_cli(state_dir, "cancel", "nope")
        assert r.returncode != 0

    def test_cancel_requires_id(self, shared_env):
        state_dir, _ = shared_env
        r = reminder_cli(state_dir, "cancel")
        assert r.returncode != 0


# --- Daemon behavior (own daemon, 1s sync) ---

class TestDaemonSync:
    def test_daemon_picks_up_new_reminder(self, tmp_path):
        state_dir = tmp_path
        (state_dir / "data" / "reminder").mkdir(parents=True)
        (state_dir / "logs" / "reminder").mkdir(parents=True)
        (state_dir / "notifications").mkdir(parents=True)
        proc = start_daemon(state_dir)
        try:
            s = parse(reminder_cli(state_dir, "set", "synced", "--in-minutes", "60"))
            time.sleep(2)
            items = parse(reminder_cli(state_dir, "list"))
            matching = [i for i in items if i["id"] == s["id"]]
            assert len(matching) == 1
            assert matching[0]["status"] == "active"
        finally:
            stop_daemon(proc)


class TestNotificationFires:
    def test_one_time_fires_and_completes(self, tmp_path):
        state_dir = tmp_path
        (state_dir / "data" / "reminder").mkdir(parents=True)
        (state_dir / "logs" / "reminder").mkdir(parents=True)
        (state_dir / "notifications").mkdir(parents=True)
        proc = start_daemon(state_dir)
        try:
            fire_at = (datetime.now(UTC) + timedelta(seconds=3)).strftime("%Y-%m-%dT%H:%M:%S")
            s = parse(reminder_cli(state_dir, "set", "fire soon", "--scheduled-datetime", fire_at, "--tz", "UTC"))
            rid = s["id"]
            time.sleep(5)

            notif_dir = state_dir / "notifications"
            notif_files = list(notif_dir.glob("*-scheduler-reminder.json"))
            assert len(notif_files) >= 1
            found = False
            for f in notif_files:
                data = json.loads(f.read_text())
                if data["reminder_id"] == rid:
                    assert data["message"] == "fire soon"
                    found = True
                    break
            assert found

            items = parse(reminder_cli(state_dir, "list"))
            assert not any(i["id"] == rid for i in items)
        finally:
            stop_daemon(proc)

    def test_recurring_stays_active(self, tmp_path):
        state_dir = tmp_path
        (state_dir / "data" / "reminder").mkdir(parents=True)
        (state_dir / "logs" / "reminder").mkdir(parents=True)
        (state_dir / "notifications").mkdir(parents=True)
        proc = start_daemon(state_dir)
        try:
            s = parse(reminder_cli(state_dir, "set", "hourly check", "--recurring", "hourly"))
            rid = s["id"]
            time.sleep(2)
            items = parse(reminder_cli(state_dir, "list"))
            assert any(i["id"] == rid for i in items)
        finally:
            stop_daemon(proc)


class TestPastDueOnRestart:
    def test_missed_reminder_on_restart(self, tmp_path):
        state_dir = tmp_path
        data_dir = state_dir / "data" / "reminder"
        notif_dir = state_dir / "notifications"
        data_dir.mkdir(parents=True)
        (state_dir / "logs" / "reminder").mkdir(parents=True)
        notif_dir.mkdir(parents=True)

        conn = sqlite3.connect(data_dir / "reminders.db")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY, message TEXT NOT NULL, schedule_type TEXT,
                scheduled_time TEXT, completed INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, trigger_data TEXT
            )
        """)
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, completed, trigger_data) VALUES (?, ?, ?, 0, ?)",
            ("pastdue01", "you missed this", f"once at {past}", json.dumps({"type": "date", "run_date": past})),
        )
        conn.commit()
        conn.close()

        proc = start_daemon(state_dir)
        try:
            time.sleep(1)
            notif_files = list(notif_dir.glob("*-scheduler-reminder.json"))
            assert len(notif_files) >= 1
            data = json.loads(notif_files[0].read_text())
            assert data["message"] == "you missed this"
            assert data["missed"] is True

            items = parse(reminder_cli(state_dir, "list"))
            assert not any(i["id"] == "pastdue01" for i in items)
        finally:
            stop_daemon(proc)


class TestDaemonLifecycle:
    def test_requires_daemon(self, tmp_path):
        state_dir = tmp_path
        (state_dir / "data" / "reminder").mkdir(parents=True)
        (state_dir / "logs" / "reminder").mkdir(parents=True)
        (state_dir / "notifications").mkdir(parents=True)
        r = reminder_cli(state_dir, "list")
        assert r.returncode != 0
        assert "daemon not running" in r.stderr.lower()

    def test_death_notification(self, tmp_path):
        state_dir = tmp_path
        (state_dir / "data" / "reminder").mkdir(parents=True)
        (state_dir / "logs" / "reminder").mkdir(parents=True)
        (state_dir / "notifications").mkdir(parents=True)
        proc = start_daemon(state_dir)
        stop_daemon(proc)

        death_files = list((state_dir / "notifications").glob("*-daemon_died.json"))
        assert len(death_files) == 1
        data = json.loads(death_files[0].read_text())
        assert data["type"] == "daemon_died"
        assert data["reason"] == "SIGTERM"

    def test_pid_file_lifecycle(self, tmp_path):
        state_dir = tmp_path
        (state_dir / "data" / "reminder").mkdir(parents=True)
        (state_dir / "logs" / "reminder").mkdir(parents=True)
        (state_dir / "notifications").mkdir(parents=True)

        pid_file = state_dir / "data" / "reminder" / "serve.pid"
        assert not pid_file.exists()

        proc = start_daemon(state_dir)
        assert pid_file.exists()
        assert int(pid_file.read_text().strip()) != 0

        stop_daemon(proc)
        assert not pid_file.exists()
