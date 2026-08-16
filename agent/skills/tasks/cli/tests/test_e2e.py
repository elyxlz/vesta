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
TASKS_BIN = str(CLI_DIR / ".venv" / "bin" / "tasks")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _env(home: Path) -> dict[str, str]:
    return {**os.environ, "HOME": str(home)}


def tasks_cli(home: Path, *args: str, timeout: float = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        [TASKS_BIN, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_env(home),
        check=False,
    )


def pidfile(home: Path) -> Path:
    return home / "agent/data/daemons/tasks.pid"


def portfile(home: Path) -> Path:
    return home / "agent/data/daemons/tasks.port"


def start_daemon(home: Path, notif_dir: Path, sync_interval: int = 1) -> subprocess.Popen:
    """Spawns the same serve child `tasks daemon start` spawns and lays down the same two
    records, because every other verb refuses to run until the pid record says a daemon is up."""
    port = _free_port()
    proc = subprocess.Popen(
        [TASKS_BIN, "serve", "--notifications-dir", str(notif_dir), "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env={**_env(home), "TASKS_SYNC_INTERVAL": str(sync_interval)},
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
    env = {**_env(home), "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}", "TASKS_SYNC_INTERVAL": "1"}
    return subprocess.run([TASKS_BIN, "daemon", action], capture_output=True, text=True, timeout=timeout, env=env, check=False)


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


# === Task CRUD ===


class TestAddTask:
    def test_add_basic(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "create", "buy milk"))
        assert data["subject"] == "buy milk"
        assert data["status"] == "pending"
        assert data["priority"] == 2

    def test_add_with_flag(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "create", "--subject", "flag title"))
        assert data["subject"] == "flag title"

    def test_add_with_priority_high(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "create", "urgent", "--priority", "high"))
        assert data["priority"] == 3

    def test_add_with_priority_low(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "create", "low prio", "--priority", "low"))
        assert data["priority"] == 1

    def test_add_with_priority_numeric(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "create", "numeric", "--priority", "3"))
        assert data["priority"] == 3

    def test_add_with_due_in_hours(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "create", "due soon", "--due-in-hours", "2"))
        assert data["due_date"] is not None

    def test_add_with_due_in_days(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "create", "due later", "--due-in-days", "7"))
        assert data["due_date"] is not None

    def test_add_with_due_in_minutes(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "create", "due asap", "--due-in-minutes", "30"))
        assert data["due_date"] is not None

    def test_add_with_datetime_and_tz(self, shared_env):
        home, _, _ = shared_env
        future = (datetime.now(UTC) + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S")
        data = parse(tasks_cli(home, "create", "timed", "--due-datetime", future, "--timezone", "UTC"))
        assert data["due_date"] is not None

    def test_add_no_due_date(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "create", "no deadline"))
        assert data["due_date"] is None

    def test_add_requires_title(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "create")
        assert r.returncode != 0

    def test_add_requires_tz_with_datetime(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "create", "test", "--due-datetime", "2025-06-15T10:00:00")
        assert r.returncode != 0
        assert "timezone" in parse(r)["error"].lower()

    def test_add_invalid_timezone(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "create", "test", "--due-datetime", "2025-06-15T10:00:00", "--timezone", "Fake/Zone")
        assert r.returncode != 0

    def test_add_rejects_negative_due(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "create", "bad", "--due-in-hours", "-1")
        assert r.returncode != 0

    def test_add_invalid_priority(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "create", "bad", "--priority", "5")
        assert r.returncode != 0

    def test_add_with_metadata(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "create", "with meta", "--initial-metadata", "some notes here"))
        assert data["metadata_path"]
        assert Path(data["metadata_path"]).exists()
        assert Path(data["metadata_path"]).read_text() == "some notes here"


class TestListTasks:
    def test_list_returns_tasks(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "list", "--json"))
        assert isinstance(items, list)
        assert len(items) >= 1

    def test_list_has_metadata_path(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "list", "--json"))
        assert all("metadata_path" in i for i in items)

    def test_list_sorted_by_priority(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "list", "--json"))
        priorities = [i["priority"] for i in items]
        assert priorities == sorted(priorities, reverse=True)


class TestGetTask:
    def test_get_by_id(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "get me", "--initial-metadata", "details"))
        data = parse(tasks_cli(home, "get", added["id"]))
        assert data["subject"] == "get me"
        assert data["metadata_content"] == "details"

    def test_get_via_flag(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "get flag"))
        data = parse(tasks_cli(home, "get", "--id", added["id"]))
        assert data["subject"] == "get flag"

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
        added = parse(tasks_cli(home, "create", "to complete"))
        data = parse(tasks_cli(home, "update", added["id"], "--status", "completed"))
        assert data["status"] == "completed"
        assert data["completed_at"] is not None

    def test_update_status_back_to_pending(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "reopen"))
        tasks_cli(home, "update", added["id"], "--status", "completed")
        data = parse(tasks_cli(home, "update", added["id"], "--status", "pending"))
        assert data["status"] == "pending"
        assert data["completed_at"] is None

    def test_update_title(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "old title"))
        data = parse(tasks_cli(home, "update", added["id"], "--subject", "new title"))
        assert data["subject"] == "new title"

    def test_update_priority(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "reprioritize"))
        data = parse(tasks_cli(home, "update", added["id"], "--priority", "high"))
        assert data["priority"] == 3

    def test_update_via_flag(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "flag update"))
        data = parse(tasks_cli(home, "update", "--id", added["id"], "--subject", "updated"))
        assert data["subject"] == "updated"

    def test_update_nonexistent(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "update", "nope", "--subject", "x")
        assert r.returncode != 0

    def test_update_requires_id(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "update", "--subject", "x")
        assert r.returncode != 0

    def test_update_invalid_status(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "bad status"))
        r = tasks_cli(home, "update", added["id"], "--status", "invalid")
        assert r.returncode != 0

    def test_update_due_in_hours(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "push me", "--due-in-hours", "1"))
        assert added["due_date"] is not None
        original_due = added["due_date"]
        data = parse(tasks_cli(home, "update", added["id"], "--due-in-days", "7"))
        assert data["due_date"] is not None
        assert data["due_date"] != original_due

    def test_update_due_datetime(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "specific time"))
        data = parse(
            tasks_cli(
                home,
                "update",
                added["id"],
                "--due-datetime",
                "2030-01-15T12:00:00",
                "--timezone",
                "UTC",
            )
        )
        assert data["due_date"] is not None
        assert "2030-01-15" in data["due_date"]


class TestDeleteTask:
    def test_delete(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "delete me"))
        data = parse(tasks_cli(home, "delete", added["id"]))
        assert data["status"] == "deleted"
        assert data["deleted_at"]

    def test_delete_hides_from_default_list(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "delete me 2"))
        tasks_cli(home, "delete", added["id"])
        items = parse(tasks_cli(home, "list", "--json"))
        assert not any(i["id"] == added["id"] for i in items)

    def test_deleted_task_shows_with_flag_marked(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "delete me 3"))
        tasks_cli(home, "delete", added["id"])
        items = parse(tasks_cli(home, "list", "--show-deleted", "--json"))
        deleted = next(i for i in items if i["id"] == added["id"])
        assert deleted["deleted_at"]
        table = tasks_cli(home, "list", "--show-deleted").stdout
        assert "[deleted]" in table

    def test_delete_keeps_metadata_file(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "with meta", "--initial-metadata", "notes"))
        meta_path = Path(added["metadata_path"])
        assert meta_path.exists()
        tasks_cli(home, "delete", added["id"])
        assert meta_path.exists()
        assert meta_path.read_text() == "notes"

    def test_get_still_finds_deleted_task(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "gone but gettable"))
        tasks_cli(home, "delete", added["id"])
        got = parse(tasks_cli(home, "get", added["id"]))
        assert got["id"] == added["id"]
        assert got["deleted_at"]

    def test_delete_via_flag(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "flag delete"))
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
        parse(tasks_cli(home, "create", "unique_searchterm_xyz"))
        items = parse(tasks_cli(home, "search", "unique_searchterm_xyz", "--json"))
        assert len(items) >= 1
        assert any("unique_searchterm_xyz" in i["subject"] for i in items)

    def test_search_no_match(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "search", "zzznonexistent999", "--json"))
        assert items == []

    def test_search_via_flag(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "search", "--query", "unique_searchterm_xyz", "--json"))
        assert len(items) >= 1

    def test_search_requires_query(self, shared_env):
        home, _, _ = shared_env
        r = tasks_cli(home, "search")
        assert r.returncode != 0

    def test_search_excludes_completed(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "searchdone_abc"))
        tasks_cli(home, "update", added["id"], "--status", "completed")
        items = parse(tasks_cli(home, "search", "searchdone_abc", "--json"))
        assert not any(i["id"] == added["id"] for i in items)

    def test_search_show_completed(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "search", "searchdone_abc", "--show-completed", "--json"))
        assert any("searchdone_abc" in i["subject"] for i in items)

    def test_search_excludes_deleted(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "searchdeleted_abc"))
        tasks_cli(home, "delete", added["id"])
        items = parse(tasks_cli(home, "search", "searchdeleted_abc", "--json"))
        assert not any(i["id"] == added["id"] for i in items)

    def test_search_show_deleted(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "search", "searchdeleted_abc", "--show-deleted", "--json"))
        assert any("searchdeleted_abc" in i["subject"] for i in items)


class TestCompletedFiltering:
    def test_list_excludes_completed(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "will complete"))
        tasks_cli(home, "update", added["id"], "--status", "completed")
        items = parse(tasks_cli(home, "list", "--json"))
        assert not any(i["id"] == added["id"] for i in items)

    def test_list_show_completed(self, shared_env):
        home, _, _ = shared_env
        items = parse(tasks_cli(home, "list", "--show-completed", "--json"))
        assert any(i["status"] == "completed" for i in items)


# === Low-friction verbs ===


class TestVerbs:
    def test_done_marks_task_done(self, shared_env):
        home, _, _ = shared_env
        task = parse(tasks_cli(home, "create", "verb done"))
        data = parse(tasks_cli(home, "done", task["id"]))
        assert data["status"] == "completed"

    def test_postpone_sets_new_due_from_now(self, shared_env):
        home, _, _ = shared_env
        task = parse(tasks_cli(home, "create", "verb postpone"))
        data = parse(tasks_cli(home, "postpone", task["id"], "--in-days", "2"))
        assert data["due_date"] is not None

    def test_postpone_without_timing_errors(self, shared_env):
        home, _, _ = shared_env
        task = parse(tasks_cli(home, "create", "verb postpone bad"))
        r = tasks_cli(home, "postpone", task["id"])
        assert r.returncode != 0


# === Daemon / Notification tests ===


class TestDaemonNotifications:
    def test_digest_fires_for_overdue_task(self, test_home):
        home, notif_dir = test_home
        proc = start_daemon(home, notif_dir)
        try:
            task = parse(tasks_cli(home, "create", "already late", "--due-in-minutes", "5"))
            past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
            conn = sqlite3.connect(home / ".tasks" / "tasks.db")
            conn.execute("UPDATE tasks SET due_date = ? WHERE id = ?", (past, task["id"]))
            conn.commit()
            conn.close()

            deadline = time.time() + 15
            digest_files = []
            while time.time() < deadline and not digest_files:
                digest_files = list(notif_dir.glob("*-tasks-task_digest.json"))
                time.sleep(0.5)
            assert digest_files, "daemon did not emit a digest for the overdue task"
            payload = json.loads(digest_files[0].read_text())
            assert task["id"] in payload["message"]
            assert "tasks postpone <id>" in payload["message"]
        finally:
            stop_daemon(proc, home)


# === Daemon lifecycle ===


class TestDaemonLifecycle:
    def test_requires_daemon(self, test_home):
        home, _ = test_home
        r = tasks_cli(home, "list")
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
        assert data["source"] == "tasks"
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


class TestNativeSurface:
    """CLI parity with the native task tools: the `create` verb, `--subject`, and status words."""

    def test_create_makes_a_task(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "create", "made with create"))
        assert data["subject"] == "made with create"
        assert data["status"] == "pending"

    def test_subject_sets_the_subject_on_create(self, shared_env):
        home, _, _ = shared_env
        data = parse(tasks_cli(home, "create", "--subject", "subject wins"))
        assert data["subject"] == "subject wins"

    def test_subject_sets_the_subject_on_update(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "before subject"))
        data = parse(tasks_cli(home, "update", added["id"], "--subject", "after subject"))
        assert data["subject"] == "after subject"

    def test_update_status_in_progress_stays_listed(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "wip via cli"))
        data = parse(tasks_cli(home, "update", added["id"], "--status", "in_progress"))
        assert data["status"] == "in_progress"
        listing = parse(tasks_cli(home, "list", "--json"))
        assert any(t["id"] == added["id"] for t in listing)

    def test_update_status_completed_closes_a_task(self, shared_env):
        home, _, _ = shared_env
        added = parse(tasks_cli(home, "create", "close via completed"))
        data = parse(tasks_cli(home, "update", added["id"], "--status", "completed"))
        assert data["status"] == "completed"
        assert data["completed_at"] is not None
