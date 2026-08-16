import json
import os
import signal
import socket
import sqlite3
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

CLI_DIR = Path(__file__).parent.parent
REMINDERS_BIN = str(CLI_DIR / ".venv" / "bin" / "reminders")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _env(home: Path) -> dict[str, str]:
    return {**os.environ, "HOME": str(home)}


def remind_cli(home: Path, *args: str, timeout: float = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        [REMINDERS_BIN, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_env(home),
        check=False,
    )


def db_path(home: Path) -> Path:
    return home / ".reminders" / "reminders.db"


def pidfile(home: Path) -> Path:
    return home / "agent/data/daemons/reminders.pid"


def portfile(home: Path) -> Path:
    return home / "agent/data/daemons/reminders.port"


def start_daemon(home: Path, notif_dir: Path, sync_interval: int = 1) -> subprocess.Popen:
    """Spawns the same serve child `reminders daemon start` spawns and lays down the same two
    records, because every other verb refuses to run until the pid record says a daemon is up."""
    port = _free_port()
    proc = subprocess.Popen(
        [REMINDERS_BIN, "serve", "--notifications-dir", str(notif_dir), "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env={**_env(home), "REMINDERS_SYNC_INTERVAL": str(sync_interval)},
    )
    line = proc.stdout.readline()
    assert "serving" in line, f"daemon failed to start: {line}"
    pidfile(home).parent.mkdir(parents=True, exist_ok=True)
    pidfile(home).write_text(str(proc.pid))
    portfile(home).write_text(str(port))
    return proc


def stop_daemon(proc: subprocess.Popen, home: Path, sig: int = signal.SIGTERM):
    os.killpg(os.getpgid(proc.pid), sig)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    pidfile(home).unlink(missing_ok=True)
    portfile(home).unlink(missing_ok=True)


def daemon_cli(home: Path, action: str, timeout: float = 60) -> subprocess.CompletedProcess:
    """Drives the real daemon verb. There is no vestad here, so a register-service stub on PATH
    hands out a port that is free right now, exactly as a registration would."""
    stub_dir = home / "stub-bin"
    stub_dir.mkdir(parents=True, exist_ok=True)
    register = stub_dir / "register-service"
    register.write_text(
        "#!/bin/sh\nexec python3 -c 'import socket; s=socket.socket(); s.bind((\"127.0.0.1\",0)); print(s.getsockname()[1]); s.close()'\n"
    )
    register.chmod(0o755)
    env = {**_env(home), "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}", "REMINDERS_SYNC_INTERVAL": "1"}
    return subprocess.run([REMINDERS_BIN, "daemon", action], capture_output=True, text=True, timeout=timeout, env=env, check=False)


def parse(result: subprocess.CompletedProcess):
    output = result.stdout.strip()
    if not output:
        output = result.stderr.strip()
    return json.loads(output)


@pytest.fixture
def test_home(tmp_path):
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    return tmp_path, notif_dir


@pytest.fixture(scope="session")
def shared_env(tmp_path_factory):
    home = tmp_path_factory.mktemp("shared")
    notif_dir = home / "notifications"
    notif_dir.mkdir()
    proc = start_daemon(home, notif_dir)
    yield home, notif_dir, proc
    stop_daemon(proc, home)


# === Reminder CRUD ===


class TestRemindSet:
    def test_set_with_minutes(self, shared_env):
        home, _, _ = shared_env
        data = parse(remind_cli(home, "create", "call mom", "--in-minutes", "30"))
        assert data["status"] == "scheduled"
        assert "30 minutes" in data["schedule"]

    def test_set_with_message_flag(self, shared_env):
        home, _, _ = shared_env
        data = parse(remind_cli(home, "create", "--message", "lunch", "--in-hours", "2"))
        assert "2 hours" in data["schedule"]

    def test_set_with_days(self, shared_env):
        home, _, _ = shared_env
        data = parse(remind_cli(home, "create", "weekly review", "--in-days", "7"))
        assert "7 days" in data["schedule"]

    def test_set_with_datetime_and_tz(self, shared_env):
        home, _, _ = shared_env
        future = (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
        data = parse(remind_cli(home, "create", "event", "--at", future, "--tz", "UTC"))
        assert data["status"] == "scheduled"
        assert "once at" in data["schedule"]

    def test_set_requires_message(self, shared_env):
        home, _, _ = shared_env
        r = remind_cli(home, "create", "--in-minutes", "5")
        assert r.returncode != 0

    def test_set_requires_time(self, shared_env):
        home, _, _ = shared_env
        r = remind_cli(home, "create", "no time")
        assert r.returncode != 0

    def test_set_rejects_negative_minutes(self, shared_env):
        home, _, _ = shared_env
        r = remind_cli(home, "create", "bad", "--in-minutes", "-5")
        assert r.returncode != 0

    def test_rejects_bare_message_without_create(self, shared_env):
        home, _, _ = shared_env
        r = remind_cli(home, "buy milk", "--in-minutes", "5")
        assert r.returncode != 0
        assert "not a subcommand" in r.stderr


class TestRemindSetRecurring:
    def test_hourly(self, shared_env):
        home, _, _ = shared_env
        data = parse(remind_cli(home, "create", "check msgs", "--recurring", "hourly"))
        assert data["schedule"] == "hourly"

    def test_daily(self, shared_env):
        home, _, _ = shared_env
        data = parse(remind_cli(home, "create", "standup", "--recurring", "daily", "--at", "2024-12-02T10:30:00", "--tz", "UTC"))
        assert "daily" in data["schedule"]
        assert "10:30" in data["schedule"]

    def test_weekly(self, shared_env):
        home, _, _ = shared_env
        data = parse(remind_cli(home, "create", "review", "--recurring", "weekly", "--at", "2024-12-06T17:00:00", "--tz", "UTC"))
        assert "weekly" in data["schedule"]
        assert "fri" in data["schedule"]

    def test_monthly(self, shared_env):
        home, _, _ = shared_env
        data = parse(remind_cli(home, "create", "bills", "--recurring", "monthly", "--at", "2024-12-15T09:00:00", "--tz", "UTC"))
        assert "monthly" in data["schedule"]
        assert "day 15" in data["schedule"]

    def test_cron(self, shared_env):
        home, _, _ = shared_env
        data = parse(remind_cli(home, "create", "weekdays 9am", "--cron", "0 9 * * 1-5", "--tz", "UTC"))
        assert data["schedule"] == "cron: 0 9 * * 1-5 (UTC)"

    def test_daily_requires_datetime(self, shared_env):
        home, _, _ = shared_env
        r = remind_cli(home, "create", "test", "--recurring", "daily")
        assert r.returncode != 0


class TestRemindList:
    def test_list_returns_items(self, shared_env):
        home, _, _ = shared_env
        parse(remind_cli(home, "create", "something", "--in-hours", "1"))
        items = parse(remind_cli(home, "list", "--json"))
        assert isinstance(items, list)
        assert len(items) >= 1

    def test_list_carries_no_task_id_field(self, shared_env):
        home, _, _ = shared_env
        parse(remind_cli(home, "create", "standalone", "--in-hours", "1"))
        items = parse(remind_cli(home, "list", "--json"))
        assert all("task_id" not in i for i in items)


class TestRemindDelete:
    def test_delete_reminder(self, shared_env):
        home, _, _ = shared_env
        s = parse(remind_cli(home, "create", "bye", "--in-minutes", "60"))
        data = parse(remind_cli(home, "delete", s["id"]))
        assert data["status"] == "deleted"

    def test_delete_removes_from_list(self, shared_env):
        home, _, _ = shared_env
        s = parse(remind_cli(home, "create", "bye2", "--in-minutes", "60"))
        remind_cli(home, "delete", s["id"])
        items = parse(remind_cli(home, "list", "--json"))
        assert not any(i["id"] == s["id"] for i in items)

    def test_delete_nonexistent(self, shared_env):
        home, _, _ = shared_env
        r = remind_cli(home, "delete", "nope")
        assert r.returncode != 0


class TestRemindUpdate:
    def test_update_message(self, shared_env):
        home, _, _ = shared_env
        s = parse(remind_cli(home, "create", "to update", "--in-minutes", "60"))
        data = parse(remind_cli(home, "update", s["id"], "--message", "updated"))
        assert data["message"] == "updated"
        assert data["status"] == "updated"

    def test_update_nonexistent(self, shared_env):
        home, _, _ = shared_env
        r = remind_cli(home, "update", "nope", "--message", "x")
        assert r.returncode != 0


class TestVerbs:
    def test_remind_snooze_moves_one_shot(self, shared_env):
        home, _, _ = shared_env
        s = parse(remind_cli(home, "create", "snooze me", "--in-hours", "1"))
        data = parse(remind_cli(home, "snooze", s["id"], "--in-hours", "5"))
        assert data["status"] == "snoozed"


# === Daemon / Notification tests ===


class TestDaemonNotifications:
    def test_reminder_fires_notification(self, test_home):
        home, notif_dir = test_home
        proc = start_daemon(home, notif_dir)
        try:
            fire_at = (datetime.now(UTC) + timedelta(seconds=3)).strftime("%Y-%m-%dT%H:%M:%S")
            s = parse(remind_cli(home, "create", "fire soon", "--at", fire_at, "--tz", "UTC"))
            rid = s["id"]
            time.sleep(6)

            notif_files = list(notif_dir.glob("*-reminders-reminder.json"))
            assert len(notif_files) >= 1
            found = False
            for f in notif_files:
                data = json.loads(f.read_text())
                if data.get("reminder_id") == rid:
                    assert data["message"].startswith("fire soon")
                    assert f"reminders snooze {rid}" in data["message"]
                    assert data["source"] == "reminders"
                    found = True
                    break
            assert found
        finally:
            stop_daemon(proc, home)

    def test_recurring_stays_active(self, test_home):
        home, notif_dir = test_home
        proc = start_daemon(home, notif_dir)
        try:
            s = parse(remind_cli(home, "create", "hourly check", "--recurring", "hourly"))
            rid = s["id"]
            time.sleep(2)
            items = parse(remind_cli(home, "list", "--json"))
            assert any(i["id"] == rid for i in items)
        finally:
            stop_daemon(proc, home)

    def test_snoozed_reminder_fires_at_new_time(self, test_home):
        home, notif_dir = test_home
        proc = start_daemon(home, notif_dir)
        try:
            far = (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
            s = parse(remind_cli(home, "create", "snooze fire", "--at", far, "--tz", "UTC"))
            time.sleep(2)  # let the daemon schedule the original far-off job
            soon = (datetime.now(UTC) + timedelta(seconds=3)).strftime("%Y-%m-%dT%H:%M:%S")
            snoozed = parse(remind_cli(home, "snooze", s["id"], "--at", soon, "--tz", "UTC"))
            assert snoozed["status"] == "snoozed"

            deadline = time.time() + 15
            found = False
            while time.time() < deadline and not found:
                found = any(json.loads(f.read_text())["reminder_id"] == s["id"] for f in notif_dir.glob("*-reminders-reminder.json"))
                time.sleep(0.5)
            assert found, "snoozed reminder did not fire at its new time"
        finally:
            stop_daemon(proc, home)


class TestMissedReminders:
    def _seed(self, home: Path):
        from reminders_cli import db as reminders_db

        data_dir = home / ".reminders"
        data_dir.mkdir(parents=True, exist_ok=True)
        reminders_db.init_db(data_dir)
        return sqlite3.connect(data_dir / "reminders.db")

    def test_missed_reminder_on_restart(self, test_home):
        """Past-due one-time reminders fire missed notifications when the daemon starts."""
        home, notif_dir = test_home
        conn = self._seed(home)
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, completed, trigger_data) VALUES (?, ?, ?, 0, ?)",
            ("pastdue01", "you missed this", f"once at {past}", json.dumps({"type": "date", "run_date": past})),
        )
        conn.commit()
        conn.close()

        proc = start_daemon(home, notif_dir)
        try:
            time.sleep(3)
            notif_files = list(notif_dir.glob("*-reminders-reminder.json"))
            assert len(notif_files) >= 1
            data = json.loads(notif_files[0].read_text())
            assert data["message"].splitlines()[0] == "you missed this"
            assert data["missed"] is True

            items = parse(remind_cli(home, "list", "--json"))
            assert not any(i["id"] == "pastdue01" for i in items)
        finally:
            stop_daemon(proc, home)

    def test_recurring_survives_restart(self, test_home):
        """Recurring reminders are restored on restart and keep scheduling (missed firings are skipped)."""
        home, notif_dir = test_home
        conn = self._seed(home)
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, completed, trigger_data) VALUES (?, ?, ?, 0, ?)",
            ("recur01", "hourly check", "hourly", json.dumps({"type": "interval", "hours": 1})),
        )
        conn.commit()
        conn.close()

        proc = start_daemon(home, notif_dir)
        try:
            time.sleep(3)
            items = parse(remind_cli(home, "list", "--json"))
            assert any(i["id"] == "recur01" for i in items)
            notif_files = list(notif_dir.glob("*-reminders-reminder.json"))
            missed = [f for f in notif_files if json.loads(f.read_text()).get("reminder_id") == "recur01"]
            assert len(missed) == 0
        finally:
            stop_daemon(proc, home)


# === Recurring reminder scheduled_time advancement ===


class TestRecurringNextRun:
    """Verify send_reminder_job advances scheduled_time for recurring reminders."""

    def _seed(self, home: Path):
        from reminders_cli import db as reminders_db

        data_dir = home / ".reminders"
        data_dir.mkdir(parents=True, exist_ok=True)
        reminders_db.init_db(data_dir)
        return sqlite3.connect(data_dir / "reminders.db")

    def test_interval_advances_scheduled_time(self, test_home):
        from reminders_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._seed(home)
        original_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("interval01", "hourly ping", "hourly", original_time, json.dumps({"type": "interval", "hours": 2})),
        )
        conn.commit()
        conn.close()

        before = datetime.now(UTC)
        send_reminder_job("interval01", message="hourly ping", data_dir=str(home / ".reminders"), notif_dir=str(notif_dir))
        after = datetime.now(UTC)

        conn = sqlite3.connect(db_path(home))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT scheduled_time FROM reminders WHERE id = 'interval01'").fetchone()
        conn.close()

        new_time = datetime.fromisoformat(row["scheduled_time"])
        assert new_time > before, "scheduled_time should advance past current time"
        assert new_time >= before + timedelta(hours=2) - timedelta(seconds=5)
        assert new_time <= after + timedelta(hours=2) + timedelta(seconds=5)

    def test_cron_advances_scheduled_time(self, test_home):
        from reminders_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._seed(home)
        original_time = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("cron01", "daily standup", "daily at 10:30 UTC", original_time, json.dumps({"type": "cron", "expr": "30 10 * * *", "tz": "UTC"})),
        )
        conn.commit()
        conn.close()

        send_reminder_job("cron01", message="daily standup", data_dir=str(home / ".reminders"), notif_dir=str(notif_dir))

        conn = sqlite3.connect(db_path(home))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT scheduled_time FROM reminders WHERE id = 'cron01'").fetchone()
        conn.close()

        new_time = datetime.fromisoformat(row["scheduled_time"])
        assert new_time > datetime.now(UTC), "scheduled_time should be in the future"
        assert new_time.hour == 10
        assert new_time.minute == 30

    def test_date_marks_completed_not_scheduled_time(self, test_home):
        from reminders_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._seed(home)
        original_time = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("date01", "one-time", f"once at {original_time}", original_time, json.dumps({"type": "date", "run_date": original_time})),
        )
        conn.commit()
        conn.close()

        send_reminder_job("date01", message="one-time", data_dir=str(home / ".reminders"), notif_dir=str(notif_dir))

        conn = sqlite3.connect(db_path(home))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT completed, scheduled_time FROM reminders WHERE id = 'date01'").fetchone()
        conn.close()

        assert row["completed"] == 1
        assert row["scheduled_time"] == original_time, "date reminder should not change scheduled_time"

    def test_nonexistent_reminder_no_crash(self, test_home):
        from reminders_cli import db as reminders_db
        from reminders_cli.commands import send_reminder_job

        home, notif_dir = test_home
        data_dir = home / ".reminders"
        data_dir.mkdir(parents=True, exist_ok=True)
        reminders_db.init_db(data_dir)

        send_reminder_job("ghost99", message="nope", data_dir=str(data_dir), notif_dir=str(notif_dir))

        notif_files = list(notif_dir.glob("*-reminders-reminder.json"))
        assert not any(json.loads(f.read_text())["reminder_id"] == "ghost99" for f in notif_files)

    def test_null_trigger_data_still_fires_notification(self, test_home):
        from reminders_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._seed(home)
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("null_td", "no trigger", "unknown", datetime.now(UTC).isoformat(), None),
        )
        conn.commit()
        conn.close()

        send_reminder_job("null_td", message="no trigger", data_dir=str(home / ".reminders"), notif_dir=str(notif_dir))

        notif_files = list(notif_dir.glob("*-reminders-reminder.json"))
        found = any(json.loads(f.read_text())["reminder_id"] == "null_td" for f in notif_files)
        assert found, "notification should still be written even without trigger_data"

    def test_db_message_overrides_kwarg(self, test_home):
        from reminders_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._seed(home)
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("msg01", "db message", "hourly", datetime.now(UTC).isoformat(), json.dumps({"type": "interval", "hours": 1})),
        )
        conn.commit()
        conn.close()

        send_reminder_job("msg01", message="kwarg message", data_dir=str(home / ".reminders"), notif_dir=str(notif_dir))

        notif_files = list(notif_dir.glob("*-reminders-reminder.json"))
        data = next(json.loads(f.read_text()) for f in notif_files if json.loads(f.read_text())["reminder_id"] == "msg01")
        assert data["message"].splitlines()[0] == "db message"


# === Daemon lifecycle ===


class TestDaemonLifecycle:
    def test_requires_daemon(self, test_home):
        home, _ = test_home
        r = remind_cli(home, "list")
        assert r.returncode != 0
        assert "daemon not running" in r.stderr.lower()

    def test_a_deliberate_stop_reports_no_death(self, test_home):
        home, notif_dir = test_home
        proc = start_daemon(home, notif_dir)
        stop_daemon(proc, home)

        assert list(notif_dir.glob("*-daemon_died.json")) == []

    def test_any_other_exit_reports_a_death(self, test_home):
        home, notif_dir = test_home
        proc = start_daemon(home, notif_dir)
        stop_daemon(proc, home, sig=signal.SIGINT)

        death_files = list(notif_dir.glob("*-daemon_died.json"))
        assert len(death_files) == 1
        data = json.loads(death_files[0].read_text())
        assert data["type"] == "daemon_died"
        assert data["source"] == "reminders"
        assert data["reason"] == "SIGINT"

    def test_the_verbs_record_and_clear_the_pid(self, test_home):
        home, _ = test_home
        assert parse(daemon_cli(home, "status")) == {"running": False, "port": None}

        assert parse(daemon_cli(home, "start")) == {"status": "started"}
        assert pidfile(home).exists()
        status = parse(daemon_cli(home, "status"))
        assert status["running"] is True
        assert status["port"] == int(portfile(home).read_text())

        assert parse(daemon_cli(home, "stop")) == {"status": "stopped"}
        assert not pidfile(home).exists()
        assert parse(daemon_cli(home, "status")) == {"running": False, "port": None}

    def test_a_second_start_never_stacks_a_daemon(self, test_home):
        home, _ = test_home
        try:
            assert parse(daemon_cli(home, "start")) == {"status": "started"}
            first = pidfile(home).read_text()
            assert parse(daemon_cli(home, "start")) == {"status": "already_running"}
            assert pidfile(home).read_text() == first
        finally:
            daemon_cli(home, "stop")

    def test_a_stop_with_nothing_running_is_a_no_op(self, test_home):
        home, _ = test_home
        assert parse(daemon_cli(home, "stop")) == {"status": "already_stopped"}
