import json
import os
import signal
import subprocess
import time
from datetime import datetime, timedelta, UTC
from pathlib import Path

import pytest

CLI_DIR = Path(__file__).parent.parent
TASKS_BIN = str(CLI_DIR / ".venv" / "bin" / "tasks")


def tasks_cli(state_dir: Path, *args: str, timeout: float = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        [TASKS_BIN, "--state-dir", str(state_dir), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def start_daemon(state_dir: Path, monitor_interval: int = 1) -> subprocess.Popen:
    proc = subprocess.Popen(
        [TASKS_BIN, "--state-dir", str(state_dir), "serve"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env={**os.environ, "TASKS_MONITOR_INTERVAL": str(monitor_interval)},
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


@pytest.fixture(scope="session")
def shared_env(tmp_path_factory):
    state_dir = tmp_path_factory.mktemp("shared")
    (state_dir / "data" / "tasks").mkdir(parents=True)
    (state_dir / "logs" / "tasks").mkdir(parents=True)
    (state_dir / "notifications").mkdir(parents=True)
    proc = start_daemon(state_dir)
    yield state_dir, proc
    stop_daemon(proc)


# --- Add ---


class TestAddTask:
    def test_add_basic(self, shared_env):
        state_dir, _ = shared_env
        data = parse(tasks_cli(state_dir, "add", "buy milk"))
        assert data["title"] == "buy milk"
        assert data["status"] == "pending"
        assert data["priority"] == 2

    def test_add_with_flag(self, shared_env):
        state_dir, _ = shared_env
        data = parse(tasks_cli(state_dir, "add", "--title", "flag title"))
        assert data["title"] == "flag title"

    def test_add_with_priority_high(self, shared_env):
        state_dir, _ = shared_env
        data = parse(tasks_cli(state_dir, "add", "urgent", "--priority", "high"))
        assert data["priority"] == 3

    def test_add_with_priority_low(self, shared_env):
        state_dir, _ = shared_env
        data = parse(tasks_cli(state_dir, "add", "low prio", "--priority", "low"))
        assert data["priority"] == 1

    def test_add_with_priority_numeric(self, shared_env):
        state_dir, _ = shared_env
        data = parse(tasks_cli(state_dir, "add", "numeric", "--priority", "3"))
        assert data["priority"] == 3

    def test_add_with_due_in_hours(self, shared_env):
        state_dir, _ = shared_env
        data = parse(tasks_cli(state_dir, "add", "due soon", "--due-in-hours", "2"))
        assert data["due_date"] is not None

    def test_add_with_due_in_days(self, shared_env):
        state_dir, _ = shared_env
        data = parse(tasks_cli(state_dir, "add", "due later", "--due-in-days", "7"))
        assert data["due_date"] is not None

    def test_add_with_due_in_minutes(self, shared_env):
        state_dir, _ = shared_env
        data = parse(tasks_cli(state_dir, "add", "due asap", "--due-in-minutes", "30"))
        assert data["due_date"] is not None

    def test_add_with_datetime_and_tz(self, shared_env):
        state_dir, _ = shared_env
        future = (datetime.now(UTC) + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S")
        data = parse(tasks_cli(state_dir, "add", "timed", "--due-datetime", future, "--timezone", "UTC"))
        assert data["due_date"] is not None

    def test_add_no_due_date(self, shared_env):
        state_dir, _ = shared_env
        data = parse(tasks_cli(state_dir, "add", "no deadline"))
        assert data["due_date"] is None

    def test_add_requires_title(self, shared_env):
        state_dir, _ = shared_env
        r = tasks_cli(state_dir, "add")
        assert r.returncode != 0

    def test_add_requires_tz_with_datetime(self, shared_env):
        state_dir, _ = shared_env
        r = tasks_cli(state_dir, "add", "test", "--due-datetime", "2025-06-15T10:00:00")
        assert r.returncode != 0
        assert "timezone" in parse(r)["error"].lower()

    def test_add_invalid_timezone(self, shared_env):
        state_dir, _ = shared_env
        r = tasks_cli(state_dir, "add", "test", "--due-datetime", "2025-06-15T10:00:00", "--timezone", "Fake/Zone")
        assert r.returncode != 0

    def test_add_rejects_negative_due(self, shared_env):
        state_dir, _ = shared_env
        r = tasks_cli(state_dir, "add", "bad", "--due-in-hours", "-1")
        assert r.returncode != 0

    def test_add_invalid_priority(self, shared_env):
        state_dir, _ = shared_env
        r = tasks_cli(state_dir, "add", "bad", "--priority", "5")
        assert r.returncode != 0

    def test_add_with_metadata(self, shared_env):
        state_dir, _ = shared_env
        data = parse(tasks_cli(state_dir, "add", "with meta", "--initial-metadata", "some notes here"))
        assert data["metadata_path"]
        assert Path(data["metadata_path"]).exists()
        assert Path(data["metadata_path"]).read_text() == "some notes here"


# --- List ---


class TestListTasks:
    def test_list_returns_tasks(self, shared_env):
        state_dir, _ = shared_env
        items = parse(tasks_cli(state_dir, "list"))
        assert isinstance(items, list)
        assert len(items) >= 1

    def test_list_has_metadata_path(self, shared_env):
        state_dir, _ = shared_env
        items = parse(tasks_cli(state_dir, "list"))
        assert all("metadata_path" in i for i in items)

    def test_list_sorted_by_priority(self, shared_env):
        state_dir, _ = shared_env
        items = parse(tasks_cli(state_dir, "list"))
        priorities = [i["priority"] for i in items]
        assert priorities == sorted(priorities, reverse=True)


# --- Get ---


class TestGetTask:
    def test_get_by_id(self, shared_env):
        state_dir, _ = shared_env
        added = parse(tasks_cli(state_dir, "add", "get me", "--initial-metadata", "details"))
        data = parse(tasks_cli(state_dir, "get", added["id"]))
        assert data["title"] == "get me"
        assert data["metadata_content"] == "details"

    def test_get_via_flag(self, shared_env):
        state_dir, _ = shared_env
        added = parse(tasks_cli(state_dir, "add", "get flag"))
        data = parse(tasks_cli(state_dir, "get", "--id", added["id"]))
        assert data["title"] == "get flag"

    def test_get_nonexistent(self, shared_env):
        state_dir, _ = shared_env
        r = tasks_cli(state_dir, "get", "nope")
        assert r.returncode != 0

    def test_get_requires_id(self, shared_env):
        state_dir, _ = shared_env
        r = tasks_cli(state_dir, "get")
        assert r.returncode != 0


# --- Update ---


class TestUpdateTask:
    def test_update_status_done(self, shared_env):
        state_dir, _ = shared_env
        added = parse(tasks_cli(state_dir, "add", "to complete"))
        data = parse(tasks_cli(state_dir, "update", added["id"], "--status", "done"))
        assert data["status"] == "done"
        assert data["completed_at"] is not None

    def test_update_status_back_to_pending(self, shared_env):
        state_dir, _ = shared_env
        added = parse(tasks_cli(state_dir, "add", "reopen"))
        tasks_cli(state_dir, "update", added["id"], "--status", "done")
        data = parse(tasks_cli(state_dir, "update", added["id"], "--status", "pending"))
        assert data["status"] == "pending"
        assert data["completed_at"] is None

    def test_update_title(self, shared_env):
        state_dir, _ = shared_env
        added = parse(tasks_cli(state_dir, "add", "old title"))
        data = parse(tasks_cli(state_dir, "update", added["id"], "--title", "new title"))
        assert data["title"] == "new title"

    def test_update_priority(self, shared_env):
        state_dir, _ = shared_env
        added = parse(tasks_cli(state_dir, "add", "reprioritize"))
        data = parse(tasks_cli(state_dir, "update", added["id"], "--priority", "high"))
        assert data["priority"] == 3

    def test_update_via_flag(self, shared_env):
        state_dir, _ = shared_env
        added = parse(tasks_cli(state_dir, "add", "flag update"))
        data = parse(tasks_cli(state_dir, "update", "--id", added["id"], "--title", "updated"))
        assert data["title"] == "updated"

    def test_update_nonexistent(self, shared_env):
        state_dir, _ = shared_env
        r = tasks_cli(state_dir, "update", "nope", "--title", "x")
        assert r.returncode != 0

    def test_update_requires_id(self, shared_env):
        state_dir, _ = shared_env
        r = tasks_cli(state_dir, "update", "--title", "x")
        assert r.returncode != 0

    def test_update_invalid_status(self, shared_env):
        state_dir, _ = shared_env
        added = parse(tasks_cli(state_dir, "add", "bad status"))
        r = tasks_cli(state_dir, "update", added["id"], "--status", "invalid")
        assert r.returncode != 0


# --- Delete ---


class TestDeleteTask:
    def test_delete(self, shared_env):
        state_dir, _ = shared_env
        added = parse(tasks_cli(state_dir, "add", "delete me"))
        data = parse(tasks_cli(state_dir, "delete", added["id"]))
        assert data["status"] == "deleted"

    def test_delete_removes_from_list(self, shared_env):
        state_dir, _ = shared_env
        added = parse(tasks_cli(state_dir, "add", "delete me 2"))
        tasks_cli(state_dir, "delete", added["id"])
        items = parse(tasks_cli(state_dir, "list"))
        assert not any(i["id"] == added["id"] for i in items)

    def test_delete_removes_metadata_file(self, shared_env):
        state_dir, _ = shared_env
        added = parse(tasks_cli(state_dir, "add", "with meta", "--initial-metadata", "notes"))
        meta_path = Path(added["metadata_path"])
        assert meta_path.exists()
        tasks_cli(state_dir, "delete", added["id"])
        assert not meta_path.exists()

    def test_delete_via_flag(self, shared_env):
        state_dir, _ = shared_env
        added = parse(tasks_cli(state_dir, "add", "flag delete"))
        data = parse(tasks_cli(state_dir, "delete", "--id", added["id"]))
        assert data["status"] == "deleted"

    def test_delete_nonexistent(self, shared_env):
        state_dir, _ = shared_env
        r = tasks_cli(state_dir, "delete", "nope")
        assert r.returncode != 0

    def test_delete_requires_id(self, shared_env):
        state_dir, _ = shared_env
        r = tasks_cli(state_dir, "delete")
        assert r.returncode != 0


# --- Search ---


class TestSearchTasks:
    def test_search_finds_match(self, shared_env):
        state_dir, _ = shared_env
        parse(tasks_cli(state_dir, "add", "unique_searchterm_xyz"))
        items = parse(tasks_cli(state_dir, "search", "unique_searchterm_xyz"))
        assert len(items) >= 1
        assert any("unique_searchterm_xyz" in i["title"] for i in items)

    def test_search_no_match(self, shared_env):
        state_dir, _ = shared_env
        items = parse(tasks_cli(state_dir, "search", "zzznonexistent999"))
        assert items == []

    def test_search_via_flag(self, shared_env):
        state_dir, _ = shared_env
        items = parse(tasks_cli(state_dir, "search", "--query", "unique_searchterm_xyz"))
        assert len(items) >= 1

    def test_search_requires_query(self, shared_env):
        state_dir, _ = shared_env
        r = tasks_cli(state_dir, "search")
        assert r.returncode != 0

    def test_search_excludes_completed(self, shared_env):
        state_dir, _ = shared_env
        added = parse(tasks_cli(state_dir, "add", "searchdone_abc"))
        tasks_cli(state_dir, "update", added["id"], "--status", "done")
        items = parse(tasks_cli(state_dir, "search", "searchdone_abc"))
        assert not any(i["id"] == added["id"] for i in items)

    def test_search_show_completed(self, shared_env):
        state_dir, _ = shared_env
        items = parse(tasks_cli(state_dir, "search", "searchdone_abc", "--show-completed"))
        assert any("searchdone_abc" in i["title"] for i in items)


# --- Completed filtering ---


class TestCompletedFiltering:
    def test_list_excludes_completed(self, shared_env):
        state_dir, _ = shared_env
        added = parse(tasks_cli(state_dir, "add", "will complete"))
        tasks_cli(state_dir, "update", added["id"], "--status", "done")
        items = parse(tasks_cli(state_dir, "list"))
        assert not any(i["id"] == added["id"] for i in items)

    def test_list_show_completed(self, shared_env):
        state_dir, _ = shared_env
        items = parse(tasks_cli(state_dir, "list", "--show-completed"))
        assert any(i["status"] == "done" for i in items)


# --- Monitor / Notifications ---


class TestMonitorNotifications:
    def test_due_soon_notification(self, tmp_path):
        state_dir = tmp_path
        (state_dir / "data" / "tasks").mkdir(parents=True)
        (state_dir / "logs" / "tasks").mkdir(parents=True)
        notif_dir = state_dir / "notifications"
        notif_dir.mkdir(parents=True)

        proc = start_daemon(state_dir, monitor_interval=1)
        try:
            due = (datetime.now(UTC) + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")
            parse(tasks_cli(state_dir, "add", "due soon task", "--due-datetime", due, "--timezone", "UTC"))
            time.sleep(3)

            notif_files = list(notif_dir.glob("*-tasks-due.json"))
            assert len(notif_files) >= 1
            data = json.loads(notif_files[0].read_text())
            assert data["type"] == "task_due"
            assert data["title"] == "due soon task"
            assert data["reminder_window"] == "15 minutes"
        finally:
            stop_daemon(proc)

    def test_no_notification_for_far_future(self, tmp_path):
        state_dir = tmp_path
        (state_dir / "data" / "tasks").mkdir(parents=True)
        (state_dir / "logs" / "tasks").mkdir(parents=True)
        notif_dir = state_dir / "notifications"
        notif_dir.mkdir(parents=True)

        proc = start_daemon(state_dir, monitor_interval=1)
        try:
            due = (datetime.now(UTC) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
            parse(tasks_cli(state_dir, "add", "far future", "--due-datetime", due, "--timezone", "UTC"))
            time.sleep(3)

            notif_files = list(notif_dir.glob("*-tasks-due.json"))
            assert len(notif_files) == 0
        finally:
            stop_daemon(proc)

    def test_no_notification_for_no_due_date(self, tmp_path):
        state_dir = tmp_path
        (state_dir / "data" / "tasks").mkdir(parents=True)
        (state_dir / "logs" / "tasks").mkdir(parents=True)
        notif_dir = state_dir / "notifications"
        notif_dir.mkdir(parents=True)

        proc = start_daemon(state_dir, monitor_interval=1)
        try:
            parse(tasks_cli(state_dir, "add", "no deadline"))
            time.sleep(3)
            notif_files = list(notif_dir.glob("*-tasks-due.json"))
            assert len(notif_files) == 0
        finally:
            stop_daemon(proc)

    def test_deduplication(self, tmp_path):
        state_dir = tmp_path
        (state_dir / "data" / "tasks").mkdir(parents=True)
        (state_dir / "logs" / "tasks").mkdir(parents=True)
        notif_dir = state_dir / "notifications"
        notif_dir.mkdir(parents=True)

        proc = start_daemon(state_dir, monitor_interval=1)
        try:
            due = (datetime.now(UTC) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S")
            parse(tasks_cli(state_dir, "add", "dedup task", "--due-datetime", due, "--timezone", "UTC"))
            time.sleep(3)

            notif_files = list(notif_dir.glob("*-tasks-due.json"))
            matching = [f for f in notif_files if "dedup task" in json.loads(f.read_text())["title"]]
            count_after_first = len(matching)
            assert count_after_first >= 1

            # Wait for another monitor cycle — count should NOT increase (deduplication)
            time.sleep(3)
            notif_files2 = list(notif_dir.glob("*-tasks-due.json"))
            matching2 = [f for f in notif_files2 if "dedup task" in json.loads(f.read_text())["title"]]
            assert len(matching2) == count_after_first
        finally:
            stop_daemon(proc)


# --- Daemon lifecycle ---


class TestDaemonLifecycle:
    def test_requires_daemon(self, tmp_path):
        state_dir = tmp_path
        (state_dir / "data" / "tasks").mkdir(parents=True)
        (state_dir / "logs" / "tasks").mkdir(parents=True)
        (state_dir / "notifications").mkdir(parents=True)
        r = tasks_cli(state_dir, "list")
        assert r.returncode != 0
        assert "daemon not running" in r.stderr.lower()

    def test_death_notification(self, tmp_path):
        state_dir = tmp_path
        (state_dir / "data" / "tasks").mkdir(parents=True)
        (state_dir / "logs" / "tasks").mkdir(parents=True)
        (state_dir / "notifications").mkdir(parents=True)
        proc = start_daemon(state_dir)
        stop_daemon(proc)

        death_files = list((state_dir / "notifications").glob("*-daemon_died.json"))
        assert len(death_files) == 1
        data = json.loads(death_files[0].read_text())
        assert data["type"] == "daemon_died"
        assert data["source"] == "tasks"

    def test_pid_file_lifecycle(self, tmp_path):
        state_dir = tmp_path
        (state_dir / "data" / "tasks").mkdir(parents=True)
        (state_dir / "logs" / "tasks").mkdir(parents=True)
        (state_dir / "notifications").mkdir(parents=True)

        pid_file = state_dir / "data" / "tasks" / "serve.pid"
        assert not pid_file.exists()

        proc = start_daemon(state_dir)
        assert pid_file.exists()

        stop_daemon(proc)
        assert not pid_file.exists()
