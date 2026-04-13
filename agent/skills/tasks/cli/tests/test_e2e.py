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
TASKS_BIN = str(CLI_DIR / ".venv" / "bin" / "tasks")


def _env(home: Path) -> dict[str, str]:
    return {**os.environ, "HOME": str(home)}


def tasks_cli(home: Path, *args: str, timeout: float = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        [TASKS_BIN, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_env(home),
    )


def start_daemon(home: Path, notif_dir: Path, sync_interval: int = 1) -> subprocess.Popen:
    proc = subprocess.Popen(
        [TASKS_BIN, "serve", "--notifications-dir", str(notif_dir)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env={**_env(home), "TASKS_SYNC_INTERVAL": str(sync_interval)},
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
    stop_daemon(proc)


# === Task CRUD ===


class TestAddTask:
    def test_add_basic(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "add", "buy milk"))
        assert data["title"] == "buy milk"
        assert data["status"] == "pending"
        assert data["priority"] == 2

    def test_add_with_flag(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "add", "--title", "flag title"))
        assert data["title"] == "flag title"

    def test_add_with_priority_high(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "add", "urgent", "--priority", "high"))
        assert data["priority"] == 3

    def test_add_with_priority_low(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "add", "low prio", "--priority", "low"))
        assert data["priority"] == 1

    def test_add_with_priority_numeric(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "add", "numeric", "--priority", "3"))
        assert data["priority"] == 3

    def test_add_with_due_in_hours(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "add", "due soon", "--due-in-hours", "2"))
        assert data["due_date"] is not None

    def test_add_with_due_in_days(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "add", "due later", "--due-in-days", "7"))
        assert data["due_date"] is not None

    def test_add_with_due_in_minutes(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "add", "due asap", "--due-in-minutes", "30"))
        assert data["due_date"] is not None

    def test_add_with_datetime_and_tz(self, shared_env):
        home, _, _ = shared_env
        future = (datetime.now(UTC) + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S")
        data = parse(tasks_cli(home, "add", "timed", "--due-datetime", future, "--timezone", "UTC"))
        assert data["due_date"] is not None

    def test_add_no_due_date(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "add", "no deadline"))
        assert data["due_date"] is None

    def test_add_requires_title(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "add")
        assert r.returncode != 0

    def test_add_requires_tz_with_datetime(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "add", "test", "--due-datetime", "2025-06-15T10:00:00")
        assert r.returncode != 0
        assert "timezone" in parse(r)["error"].lower()

    def test_add_invalid_timezone(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "add", "test", "--due-datetime", "2025-06-15T10:00:00", "--timezone", "Fake/Zone")
        assert r.returncode != 0

    def test_add_rejects_negative_due(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "add", "bad", "--due-in-hours", "-1")
        assert r.returncode != 0

    def test_add_invalid_priority(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "add", "bad", "--priority", "5")
        assert r.returncode != 0

    def test_add_with_metadata(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "add", "with meta", "--initial-metadata", "some notes here"))
        assert data["metadata_path"]
        assert Path(data["metadata_path"]).exists()
        assert Path(data["metadata_path"]).read_text() == "some notes here"


class TestListTasks:
    def test_list_returns_tasks(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "list"))
        assert isinstance(items, list)
        assert len(items) >= 1

    def test_list_has_metadata_path(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "list"))
        assert all("metadata_path" in i for i in items)

    def test_list_sorted_by_priority(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "list"))
        priorities = [i["priority"] for i in items]
        assert priorities == sorted(priorities, reverse=True)


class TestGetTask:
    def test_get_by_id(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "add", "get me", "--initial-metadata", "details"))
        data = parse(tasks_cli(home, "get", added["id"]))
        assert data["title"] == "get me"
        assert data["metadata_content"] == "details"

    def test_get_via_flag(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "add", "get flag"))
        data = parse(tasks_cli(home, "get", "--id", added["id"]))
        assert data["title"] == "get flag"

    def test_get_nonexistent(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "get", "nope")
        assert r.returncode != 0

    def test_get_requires_id(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "get")
        assert r.returncode != 0


class TestUpdateTask:
    def test_update_status_done(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "add", "to complete"))
        data = parse(tasks_cli(home, "update", added["id"], "--status", "done"))
        assert data["status"] == "done"
        assert data["completed_at"] is not None

    def test_update_status_back_to_pending(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "add", "reopen"))
        tasks_cli(home, "update", added["id"], "--status", "done")
        data = parse(tasks_cli(home, "update", added["id"], "--status", "pending"))
        assert data["status"] == "pending"
        assert data["completed_at"] is None

    def test_update_title(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "add", "old title"))
        data = parse(tasks_cli(home, "update", added["id"], "--title", "new title"))
        assert data["title"] == "new title"

    def test_update_priority(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "add", "reprioritize"))
        data = parse(tasks_cli(home, "update", added["id"], "--priority", "high"))
        assert data["priority"] == 3

    def test_update_via_flag(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "add", "flag update"))
        data = parse(tasks_cli(home, "update", "--id", added["id"], "--title", "updated"))
        assert data["title"] == "updated"

    def test_update_nonexistent(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "update", "nope", "--title", "x")
        assert r.returncode != 0

    def test_update_requires_id(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "update", "--title", "x")
        assert r.returncode != 0

    def test_update_invalid_status(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "add", "bad status"))
        r = tasks_cli(home, "update", added["id"], "--status", "invalid")
        assert r.returncode != 0


class TestDeleteTask:
    def test_delete(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "add", "delete me"))
        data = parse(tasks_cli(home, "delete", added["id"]))
        assert data["status"] == "deleted"

    def test_delete_removes_from_list(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "add", "delete me 2"))
        tasks_cli(home, "delete", added["id"])
        items = parse(tasks_cli(home, "list"))
        assert not any(i["id"] == added["id"] for i in items)

    def test_delete_removes_metadata_file(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "add", "with meta", "--initial-metadata", "notes"))
        meta_path = Path(added["metadata_path"])
        assert meta_path.exists()
        tasks_cli(home, "delete", added["id"])
        assert not meta_path.exists()

    def test_delete_via_flag(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "add", "flag delete"))
        data = parse(tasks_cli(home, "delete", "--id", added["id"]))
        assert data["status"] == "deleted"

    def test_delete_nonexistent(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "delete", "nope")
        assert r.returncode != 0

    def test_delete_requires_id(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "delete")
        assert r.returncode != 0


class TestSearchTasks:
    def test_search_finds_match(self, shared_env):
        home, _, _ = shared_env
        parse(tasks_cli(home, "add", "unique_searchterm_xyz"))
        items = parse(tasks_cli(home, "search", "unique_searchterm_xyz"))
        assert len(items) >= 1
        assert any("unique_searchterm_xyz" in i["title"] for i in items)

    def test_search_no_match(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "search", "zzznonexistent999"))
        assert items == []

    def test_search_via_flag(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "search", "--query", "unique_searchterm_xyz"))
        assert len(items) >= 1

    def test_search_requires_query(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "search")
        assert r.returncode != 0

    def test_search_excludes_completed(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "add", "searchdone_abc"))
        tasks_cli(home, "update", added["id"], "--status", "done")
        items = parse(tasks_cli(home, "search", "searchdone_abc"))
        assert not any(i["id"] == added["id"] for i in items)

    def test_search_show_completed(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "search", "searchdone_abc", "--show-completed"))
        assert any("searchdone_abc" in i["title"] for i in items)


class TestCompletedFiltering:
    def test_list_excludes_completed(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "add", "will complete"))
        tasks_cli(home, "update", added["id"], "--status", "done")
        items = parse(tasks_cli(home, "list"))
        assert not any(i["id"] == added["id"] for i in items)

    def test_list_show_completed(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "list", "--show-completed"))
        assert any(i["status"] == "done" for i in items)


# === Reminder CRUD ===


class TestRemindSet:
    def test_set_standalone_with_minutes(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "remind", "call mom", "--in-minutes", "30"))
        assert data["status"] == "scheduled"
        assert "30 minutes" in data["schedule"]
        assert data["task_id"] is None

    def test_set_standalone_with_hours(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "remind", "--message", "lunch", "--in-hours", "2"))
        assert "2 hours" in data["schedule"]

    def test_set_standalone_with_days(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "remind", "weekly review", "--in-days", "7"))
        assert "7 days" in data["schedule"]

    def test_set_with_datetime_and_tz(self, shared_env):
        home, _, _ = shared_env
        future = (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
        data = parse(tasks_cli(home, "remind", "event", "--at", future, "--tz", "UTC"))
        assert data["status"] == "scheduled"
        assert "once at" in data["schedule"]

    def test_set_linked_to_task(self, shared_env):
        home, _, _ = shared_env
        task = parse(tasks_cli(home, "add", "linked task"))
        data = parse(tasks_cli(home, "remind", "check this", "--task", task["id"], "--in-hours", "1"))
        assert data["task_id"] == task["id"]
        assert data["status"] == "scheduled"

    def test_set_requires_message(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "remind", "--in-minutes", "5")
        assert r.returncode != 0

    def test_set_requires_time(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "remind", "no time")
        assert r.returncode != 0

    def test_set_rejects_invalid_task_id(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "remind", "bad link", "--task", "nonexistent", "--in-minutes", "5")
        assert r.returncode != 0

    def test_set_rejects_negative_minutes(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "remind", "bad", "--in-minutes", "-5")
        assert r.returncode != 0


class TestRemindSetRecurring:
    def test_hourly(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "remind", "check msgs", "--recurring", "hourly"))
        assert data["schedule"] == "hourly"

    def test_daily(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "remind", "standup", "--recurring", "daily", "--at", "2024-12-02T10:30:00", "--tz", "UTC"))
        assert "daily" in data["schedule"]
        assert "10:30" in data["schedule"]

    def test_weekly(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "remind", "review", "--recurring", "weekly", "--at", "2024-12-06T17:00:00", "--tz", "UTC"))
        assert "weekly" in data["schedule"]
        assert "fri" in data["schedule"]

    def test_monthly(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "remind", "bills", "--recurring", "monthly", "--at", "2024-12-15T09:00:00", "--tz", "UTC"))
        assert "monthly" in data["schedule"]
        assert "day 15" in data["schedule"]

    def test_yearly(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "remind", "birthday", "--recurring", "yearly", "--at", "2024-03-14T12:00:00", "--tz", "UTC"))
        assert "yearly" in data["schedule"]

    def test_daily_requires_datetime(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "remind", "test", "--recurring", "daily")
        assert r.returncode != 0


class TestRemindList:
    def test_list_returns_items(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "remind", "list"))
        assert isinstance(items, list)
        assert len(items) >= 1

    def test_list_filter_by_task(self, shared_env):
        home, _, _ = shared_env
        task = parse(tasks_cli(home, "add", "filter task"))
        parse(tasks_cli(home, "remind", "linked reminder", "--task", task["id"], "--in-hours", "2"))
        parse(tasks_cli(home, "remind", "unlinked reminder", "--in-hours", "2"))
        items = parse(tasks_cli(home, "remind", "list", "--task", task["id"]))
        assert all(i["task_id"] == task["id"] for i in items)

    def test_list_has_auto_generated_field(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "remind", "list"))
        assert all("auto_generated" in i for i in items)


class TestRemindDelete:
    def test_delete_reminder(self, shared_env):
        home, _, _ = shared_env
        s = parse(tasks_cli(home, "remind", "bye", "--in-minutes", "60"))
        data = parse(tasks_cli(home, "remind", "delete", s["id"]))
        assert data["status"] == "deleted"

    def test_delete_removes_from_list(self, shared_env):
        home, _, _ = shared_env
        s = parse(tasks_cli(home, "remind", "bye2", "--in-minutes", "60"))
        tasks_cli(home, "remind", "delete", s["id"])
        items = parse(tasks_cli(home, "remind", "list"))
        assert not any(i["id"] == s["id"] for i in items)

    def test_delete_nonexistent(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "remind", "delete", "nope")
        assert r.returncode != 0

    def test_delete_does_not_affect_task(self, shared_env):
        home, _, _ = shared_env
        task = parse(tasks_cli(home, "add", "survives"))
        s = parse(tasks_cli(home, "remind", "linked delete test", "--task", task["id"], "--in-hours", "1"))
        tasks_cli(home, "remind", "delete", s["id"])
        # Task should still exist
        data = parse(tasks_cli(home, "get", task["id"]))
        assert data["title"] == "survives"


class TestRemindUpdate:
    def test_update_message(self, shared_env):
        home, _, _ = shared_env
        s = parse(tasks_cli(home, "remind", "to update", "--in-minutes", "60"))
        data = parse(tasks_cli(home, "remind", "update", s["id"], "--message", "updated"))
        assert data["message"] == "updated"
        assert data["status"] == "updated"

    def test_update_nonexistent(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "remind", "update", "nope", "--message", "x")
        assert r.returncode != 0


# === Cascade deletion ===


class TestCascadeDeletion:
    def test_delete_task_cascades_reminders(self, shared_env):
        home, _, _ = shared_env
        task = parse(tasks_cli(home, "add", "cascade test"))
        r1 = parse(tasks_cli(home, "remind", "linked 1", "--task", task["id"], "--in-hours", "1"))
        r2 = parse(tasks_cli(home, "remind", "linked 2", "--task", task["id"], "--in-hours", "2"))

        tasks_cli(home, "delete", task["id"])

        items = parse(tasks_cli(home, "remind", "list"))
        ids = [i["id"] for i in items]
        assert r1["id"] not in ids
        assert r2["id"] not in ids


# === Auto-generated reminders ===


class TestAutoReminders:
    def test_due_date_creates_auto_reminders(self, shared_env):
        home, _, _ = shared_env
        future = (datetime.now(UTC) + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")
        task = parse(tasks_cli(home, "add", "auto reminder task", "--due-datetime", future, "--timezone", "UTC"))
        items = parse(tasks_cli(home, "remind", "list", "--task", task["id"]))
        auto = [i for i in items if i["auto_generated"]]
        # Should have reminders for 1 week, 1 day, 1 hour, 15 min before
        assert len(auto) >= 3  # at least 1 week, 1 day, 1 hour (15 min depends on timing)

    def test_auto_reminders_skipped_if_past(self, shared_env):
        home, _, _ = shared_env
        # Due in 30 minutes: only 15-min auto-reminder should be created (others are in the past)
        future = (datetime.now(UTC) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
        task = parse(tasks_cli(home, "add", "soon task", "--due-datetime", future, "--timezone", "UTC"))
        items = parse(tasks_cli(home, "remind", "list", "--task", task["id"]))
        auto = [i for i in items if i["auto_generated"]]
        assert len(auto) == 1
        assert "15 minutes" in auto[0]["message"]

    def test_done_status_cleans_auto_reminders(self, shared_env):
        home, _, _ = shared_env
        future = (datetime.now(UTC) + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")
        task = parse(tasks_cli(home, "add", "done cleanup", "--due-datetime", future, "--timezone", "UTC"))
        # Verify auto reminders exist
        items = parse(tasks_cli(home, "remind", "list", "--task", task["id"]))
        assert any(i["auto_generated"] for i in items)
        # Mark done
        tasks_cli(home, "update", task["id"], "--status", "done")
        # Auto reminders should be gone
        items = parse(tasks_cli(home, "remind", "list", "--task", task["id"]))
        auto = [i for i in items if i["auto_generated"]]
        assert len(auto) == 0

    def test_cascade_deletes_auto_reminders(self, shared_env):
        home, _, _ = shared_env
        future = (datetime.now(UTC) + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")
        task = parse(tasks_cli(home, "add", "cascade auto", "--due-datetime", future, "--timezone", "UTC"))
        items = parse(tasks_cli(home, "remind", "list", "--task", task["id"]))
        assert len(items) >= 1
        tasks_cli(home, "delete", task["id"])
        # All reminders for this task should be gone
        all_items = parse(tasks_cli(home, "remind", "list"))
        assert not any(i["task_id"] == task["id"] for i in all_items)


# === Daemon / Notification tests ===


class TestDaemonNotifications:
    def test_reminder_fires_notification(self, test_home):
        home, notif_dir = test_home
        proc = start_daemon(home, notif_dir)
        try:
            fire_at = (datetime.now(UTC) + timedelta(seconds=3)).strftime("%Y-%m-%dT%H:%M:%S")
            s = parse(tasks_cli(home, "remind", "fire soon", "--at", fire_at, "--tz", "UTC"))
            rid = s["id"]
            time.sleep(6)

            notif_files = list(notif_dir.glob("*-tasks-reminder.json"))
            assert len(notif_files) >= 1
            found = False
            for f in notif_files:
                data = json.loads(f.read_text())
                if data.get("reminder_id") == rid:
                    assert data["message"] == "fire soon"
                    assert data["source"] == "tasks"
                    found = True
                    break
            assert found
        finally:
            stop_daemon(proc)

    def test_recurring_stays_active(self, test_home):
        home, notif_dir = test_home
        proc = start_daemon(home, notif_dir)
        try:
            s = parse(tasks_cli(home, "remind", "hourly check", "--recurring", "hourly"))
            rid = s["id"]
            time.sleep(2)
            items = parse(tasks_cli(home, "remind", "list"))
            assert any(i["id"] == rid for i in items)
        finally:
            stop_daemon(proc)


class TestMissedReminders:
    def _setup_db(self, home):
        """Create a fresh tasks DB with schema v2 for manual insertion tests."""
        data_dir = home / ".tasks"
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "tasks.db")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
        conn.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (2)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, title TEXT NOT NULL,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'done')),
                priority INTEGER DEFAULT 2 CHECK(priority IN (1, 2, 3)),
                due_date TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY, task_id TEXT, message TEXT NOT NULL,
                schedule_type TEXT, scheduled_time TEXT, completed INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, trigger_data TEXT,
                auto_generated INTEGER DEFAULT 0,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            )
        """)
        return conn

    def test_missed_reminder_on_restart(self, test_home):
        """Past-due one-time reminders fire missed notifications when daemon starts."""
        home, notif_dir = test_home
        conn = self._setup_db(home)
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
            notif_files = list(notif_dir.glob("*-tasks-reminder.json"))
            assert len(notif_files) >= 1
            data = json.loads(notif_files[0].read_text())
            assert data["message"] == "you missed this"
            assert data["missed"] is True

            items = parse(tasks_cli(home, "remind", "list"))
            assert not any(i["id"] == "pastdue01" for i in items)
        finally:
            stop_daemon(proc)

    def test_recurring_survives_restart(self, test_home):
        """Recurring reminders are restored on restart and keep scheduling (missed firings are skipped)."""
        home, notif_dir = test_home
        conn = self._setup_db(home)
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, completed, trigger_data) VALUES (?, ?, ?, 0, ?)",
            ("recur01", "hourly check", "hourly", json.dumps({"type": "interval", "hours": 1})),
        )
        conn.commit()
        conn.close()

        proc = start_daemon(home, notif_dir)
        try:
            time.sleep(3)
            # Recurring reminder should be active, not marked completed or missed
            items = parse(tasks_cli(home, "remind", "list"))
            assert any(i["id"] == "recur01" for i in items)
            # No missed notification should be written for recurring reminders
            notif_files = list(notif_dir.glob("*-tasks-reminder.json"))
            missed = [f for f in notif_files if json.loads(f.read_text()).get("reminder_id") == "recur01"]
            assert len(missed) == 0
        finally:
            stop_daemon(proc)


# === Recurring reminder scheduled_time advancement ===


class TestRecurringNextRun:
    """Verify send_reminder_job advances scheduled_time for recurring reminders."""

    def _setup_db(self, home):
        data_dir = home / ".tasks"
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(data_dir / "tasks.db")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
        conn.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (2)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, title TEXT NOT NULL,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'done')),
                priority INTEGER DEFAULT 2 CHECK(priority IN (1, 2, 3)),
                due_date TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY, task_id TEXT, message TEXT NOT NULL,
                schedule_type TEXT, scheduled_time TEXT, completed INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, trigger_data TEXT,
                auto_generated INTEGER DEFAULT 0,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            )
        """)
        return conn

    def test_interval_advances_scheduled_time(self, test_home):
        """After firing, interval reminder scheduled_time moves to now + interval."""
        from tasks_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._setup_db(home)
        original_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("interval01", "hourly ping", "hourly", original_time, json.dumps({"type": "interval", "hours": 2})),
        )
        conn.commit()
        conn.close()

        before = datetime.now(UTC)
        send_reminder_job("interval01", message="hourly ping", data_dir=str(home / ".tasks"), notif_dir=str(notif_dir))
        after = datetime.now(UTC)

        conn = sqlite3.connect(home / ".tasks" / "tasks.db")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT scheduled_time FROM reminders WHERE id = 'interval01'").fetchone()
        conn.close()

        new_time = datetime.fromisoformat(row["scheduled_time"])
        assert new_time > before, "scheduled_time should advance past current time"
        assert new_time >= before + timedelta(hours=2) - timedelta(seconds=5)
        assert new_time <= after + timedelta(hours=2) + timedelta(seconds=5)

    def test_cron_advances_scheduled_time(self, test_home):
        """After firing, cron reminder scheduled_time moves to next cron occurrence."""
        from tasks_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._setup_db(home)
        original_time = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("cron01", "daily standup", "daily at 10:30 UTC", original_time, json.dumps({"type": "cron", "hour": 10, "minute": 30})),
        )
        conn.commit()
        conn.close()

        send_reminder_job("cron01", message="daily standup", data_dir=str(home / ".tasks"), notif_dir=str(notif_dir))

        conn = sqlite3.connect(home / ".tasks" / "tasks.db")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT scheduled_time FROM reminders WHERE id = 'cron01'").fetchone()
        conn.close()

        new_time = datetime.fromisoformat(row["scheduled_time"])
        assert new_time > datetime.now(UTC), "scheduled_time should be in the future"
        assert new_time.hour == 10
        assert new_time.minute == 30

    def test_date_marks_completed_not_scheduled_time(self, test_home):
        """One-time date reminders get completed, not rescheduled."""
        from tasks_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._setup_db(home)
        original_time = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("date01", "one-time", f"once at {original_time}", original_time, json.dumps({"type": "date", "run_date": original_time})),
        )
        conn.commit()
        conn.close()

        send_reminder_job("date01", message="one-time", data_dir=str(home / ".tasks"), notif_dir=str(notif_dir))

        conn = sqlite3.connect(home / ".tasks" / "tasks.db")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT completed, scheduled_time FROM reminders WHERE id = 'date01'").fetchone()
        conn.close()

        assert row["completed"] == 1
        assert row["scheduled_time"] == original_time, "date reminder should not change scheduled_time"

    def test_interval_fires_notification_and_advances(self, test_home):
        """Interval reminder both writes notification and advances scheduled_time."""
        from tasks_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._setup_db(home)
        original_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("interval02", "check email", "hourly", original_time, json.dumps({"type": "interval", "hours": 1})),
        )
        conn.commit()
        conn.close()

        send_reminder_job("interval02", message="check email", data_dir=str(home / ".tasks"), notif_dir=str(notif_dir))

        notif_files = list(notif_dir.glob("*-tasks-reminder.json"))
        found = any(json.loads(f.read_text())["reminder_id"] == "interval02" for f in notif_files)
        assert found, "notification should be written"

        conn = sqlite3.connect(home / ".tasks" / "tasks.db")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT completed, scheduled_time FROM reminders WHERE id = 'interval02'").fetchone()
        conn.close()

        assert row["completed"] == 0, "interval reminder should stay active"
        assert datetime.fromisoformat(row["scheduled_time"]) > datetime.now(UTC)

    def test_nonexistent_reminder_no_crash(self, test_home):
        """Firing a reminder ID that doesn't exist in the DB should not crash."""
        from tasks_cli.commands import send_reminder_job
        from tasks_cli import db as tasks_db

        home, notif_dir = test_home
        data_dir = home / ".tasks"
        data_dir.mkdir(parents=True, exist_ok=True)
        tasks_db.init_db(data_dir)

        send_reminder_job("ghost99", message="nope", data_dir=str(data_dir), notif_dir=str(notif_dir))

        notif_files = list(notif_dir.glob("*-tasks-reminder.json"))
        assert not any(json.loads(f.read_text())["reminder_id"] == "ghost99" for f in notif_files)

    def test_null_trigger_data_still_fires_notification(self, test_home):
        """Reminder with NULL trigger_data should fire notification without crashing."""
        from tasks_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._setup_db(home)
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("null_td", "no trigger", "unknown", datetime.now(UTC).isoformat(), None),
        )
        conn.commit()
        conn.close()

        send_reminder_job("null_td", message="no trigger", data_dir=str(home / ".tasks"), notif_dir=str(notif_dir))

        notif_files = list(notif_dir.glob("*-tasks-reminder.json"))
        found = any(json.loads(f.read_text())["reminder_id"] == "null_td" for f in notif_files)
        assert found, "notification should still be written even without trigger_data"

    def test_unknown_trigger_type_no_scheduled_time_change(self, test_home):
        """Unknown trigger type should fire notification but not modify scheduled_time."""
        from tasks_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._setup_db(home)
        original_time = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("unknown01", "mystery", "custom", original_time, json.dumps({"type": "alien"})),
        )
        conn.commit()
        conn.close()

        send_reminder_job("unknown01", message="mystery", data_dir=str(home / ".tasks"), notif_dir=str(notif_dir))

        conn = sqlite3.connect(home / ".tasks" / "tasks.db")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT completed, scheduled_time FROM reminders WHERE id = 'unknown01'").fetchone()
        conn.close()

        assert row["completed"] == 0, "unknown type should not mark completed"
        assert row["scheduled_time"] == original_time, "unknown type should not change scheduled_time"

    def test_interval_defaults_to_one_hour(self, test_home):
        """Interval trigger without 'hours' key should default to 1 hour."""
        from tasks_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._setup_db(home)
        original_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("interval_default", "default hours", "hourly", original_time, json.dumps({"type": "interval"})),
        )
        conn.commit()
        conn.close()

        before = datetime.now(UTC)
        send_reminder_job("interval_default", message="default hours", data_dir=str(home / ".tasks"), notif_dir=str(notif_dir))
        after = datetime.now(UTC)

        conn = sqlite3.connect(home / ".tasks" / "tasks.db")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT scheduled_time FROM reminders WHERE id = 'interval_default'").fetchone()
        conn.close()

        new_time = datetime.fromisoformat(row["scheduled_time"])
        assert new_time >= before + timedelta(hours=1) - timedelta(seconds=5)
        assert new_time <= after + timedelta(hours=1) + timedelta(seconds=5)

    def test_empty_notif_dir_skips_everything(self, test_home):
        """Empty string notif_dir should skip all processing."""
        from tasks_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._setup_db(home)
        original_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("skip01", "should skip", "hourly", original_time, json.dumps({"type": "interval", "hours": 1})),
        )
        conn.commit()
        conn.close()

        send_reminder_job("skip01", message="should skip", data_dir=str(home / ".tasks"), notif_dir="")

        conn = sqlite3.connect(home / ".tasks" / "tasks.db")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT scheduled_time, completed FROM reminders WHERE id = 'skip01'").fetchone()
        conn.close()

        assert row["scheduled_time"] == original_time, "scheduled_time should not change with empty notif_dir"
        assert row["completed"] == 0

    def test_cron_weekly_advances_to_correct_day(self, test_home):
        """Weekly cron reminder should advance to the correct day of week."""
        from tasks_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._setup_db(home)
        original_time = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("cron_weekly", "friday review", "weekly on fri at 17:00 UTC", original_time,
             json.dumps({"type": "cron", "day_of_week": "fri", "hour": 17, "minute": 0})),
        )
        conn.commit()
        conn.close()

        send_reminder_job("cron_weekly", message="friday review", data_dir=str(home / ".tasks"), notif_dir=str(notif_dir))

        conn = sqlite3.connect(home / ".tasks" / "tasks.db")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT scheduled_time FROM reminders WHERE id = 'cron_weekly'").fetchone()
        conn.close()

        new_time = datetime.fromisoformat(row["scheduled_time"])
        assert new_time > datetime.now(UTC)
        assert new_time.weekday() == 4, "should be a Friday (weekday 4)"
        assert new_time.hour == 17
        assert new_time.minute == 0

    def test_cron_monthly_advances_to_correct_day(self, test_home):
        """Monthly cron reminder should advance to the correct day of month."""
        from tasks_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._setup_db(home)
        original_time = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("cron_monthly", "pay bills", "monthly on day 15 at 09:00 UTC", original_time,
             json.dumps({"type": "cron", "day": 15, "hour": 9, "minute": 0})),
        )
        conn.commit()
        conn.close()

        send_reminder_job("cron_monthly", message="pay bills", data_dir=str(home / ".tasks"), notif_dir=str(notif_dir))

        conn = sqlite3.connect(home / ".tasks" / "tasks.db")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT scheduled_time FROM reminders WHERE id = 'cron_monthly'").fetchone()
        conn.close()

        new_time = datetime.fromisoformat(row["scheduled_time"])
        assert new_time > datetime.now(UTC)
        assert new_time.day == 15
        assert new_time.hour == 9

    def test_consecutive_fires_keep_advancing(self, test_home):
        """Calling send_reminder_job multiple times should advance scheduled_time each time."""
        from tasks_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._setup_db(home)
        original_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("multi01", "repeat", "hourly", original_time, json.dumps({"type": "interval", "hours": 1})),
        )
        conn.commit()
        conn.close()

        send_reminder_job("multi01", message="repeat", data_dir=str(home / ".tasks"), notif_dir=str(notif_dir))

        conn = sqlite3.connect(home / ".tasks" / "tasks.db")
        conn.row_factory = sqlite3.Row
        first_time = datetime.fromisoformat(
            conn.execute("SELECT scheduled_time FROM reminders WHERE id = 'multi01'").fetchone()["scheduled_time"]
        )
        conn.close()

        send_reminder_job("multi01", message="repeat", data_dir=str(home / ".tasks"), notif_dir=str(notif_dir))

        conn = sqlite3.connect(home / ".tasks" / "tasks.db")
        conn.row_factory = sqlite3.Row
        second_time = datetime.fromisoformat(
            conn.execute("SELECT scheduled_time FROM reminders WHERE id = 'multi01'").fetchone()["scheduled_time"]
        )
        conn.close()

        assert second_time > first_time, "second fire should advance past first fire's scheduled_time"

    def test_db_message_overrides_kwarg(self, test_home):
        """Message from DB row should take precedence over the kwarg."""
        from tasks_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._setup_db(home)
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("msg01", "db message", "hourly", datetime.now(UTC).isoformat(), json.dumps({"type": "interval", "hours": 1})),
        )
        conn.commit()
        conn.close()

        send_reminder_job("msg01", message="kwarg message", data_dir=str(home / ".tasks"), notif_dir=str(notif_dir))

        notif_files = list(notif_dir.glob("*-tasks-reminder.json"))
        data = next(json.loads(f.read_text()) for f in notif_files if json.loads(f.read_text())["reminder_id"] == "msg01")
        assert data["message"] == "db message"

    def test_empty_db_message_falls_back_to_kwarg(self, test_home):
        """If DB message is empty string, the kwarg message should be used."""
        from tasks_cli.commands import send_reminder_job

        home, notif_dir = test_home
        conn = self._setup_db(home)
        conn.execute(
            "INSERT INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            ("msg02", "", "hourly", datetime.now(UTC).isoformat(), json.dumps({"type": "interval", "hours": 1})),
        )
        conn.commit()
        conn.close()

        send_reminder_job("msg02", message="fallback msg", data_dir=str(home / ".tasks"), notif_dir=str(notif_dir))

        notif_files = list(notif_dir.glob("*-tasks-reminder.json"))
        data = next(json.loads(f.read_text()) for f in notif_files if json.loads(f.read_text())["reminder_id"] == "msg02")
        assert data["message"] == "fallback msg"


# === Daemon lifecycle ===


class TestDaemonLifecycle:
    def test_requires_daemon(self, test_home):
        home, _ = test_home
        r = tasks_cli(home, "list")
        assert r.returncode != 0
        assert "daemon not running" in r.stderr.lower()

    def test_death_notification(self, test_home):
        home, notif_dir = test_home
        proc = start_daemon(home, notif_dir)
        stop_daemon(proc)

        death_files = list(notif_dir.glob("*-daemon_died.json"))
        assert len(death_files) == 1
        data = json.loads(death_files[0].read_text())
        assert data["type"] == "daemon_died"
        assert data["source"] == "tasks"

    def test_pid_file_lifecycle(self, test_home):
        home, notif_dir = test_home
        pid_file = home / ".tasks" / "serve.pid"
        assert not pid_file.exists()

        proc = start_daemon(home, notif_dir)
        assert pid_file.exists()

        stop_daemon(proc)
        assert not pid_file.exists()
