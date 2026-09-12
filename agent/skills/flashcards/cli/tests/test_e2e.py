import concurrent.futures
import json
import os
import signal
import socket
import subprocess
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

CLI_DIR = Path(__file__).parent.parent
FLASHCARDS_BIN = str(CLI_DIR / ".venv" / "bin" / "flashcards")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _env(home: Path) -> dict[str, str]:
    return {**os.environ, "HOME": str(home), "TZ": "UTC", "FLASHCARDS_TICK_SECS": "1"}


def _cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([FLASHCARDS_BIN, *args], capture_output=True, text=True, timeout=30, env=_env(home), check=False)


def _wait_for(url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise AssertionError(f"{url} never answered")


def _request(url: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read())


def _active_hours_around_now() -> str:
    """A nudge window that holds the daemon's clock (UTC, per _env) whatever hour the test runs."""
    now = datetime.now(UTC)
    return f"{(now - timedelta(hours=1)):%H:%M}-{(now + timedelta(hours=1)):%H:%M}"


def _serve(home: Path, *args: str) -> subprocess.Popen:
    return subprocess.Popen(
        [FLASHCARDS_BIN, "serve", "--notifications-dir", str(home / "agent/notifications"), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=_env(home),
    )


def _end(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


def _await_nudge(home: Path, proc: subprocess.Popen) -> Path:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not list((home / "agent/notifications").glob("*cards_due.json")):
        assert proc.poll() is None, proc.stderr.read() if proc.stderr else ""
        time.sleep(0.2)
    (notif,) = (home / "agent/notifications").glob("*cards_due.json")
    return notif


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "agent/notifications").mkdir(parents=True)
    assert _cli(tmp_path, "config", "active_hours", _active_hours_around_now()).returncode == 0
    return tmp_path


@pytest.fixture
def serving(home: Path):
    port = _free_port()
    proc = _serve(home, "--port", str(port))
    try:
        _wait_for(f"http://127.0.0.1:{port}/stats")
        yield f"http://127.0.0.1:{port}", proc
    finally:
        _end(proc)


def test_cli_round_trip(home: Path):
    added = _cli(home, "add", "--deck", "spanish", "hola", "hello")
    assert added.returncode == 0, added.stderr
    assert json.loads(added.stdout)["ids"] == [1]
    nxt = json.loads(_cli(home, "next").stdout)
    assert nxt["front"] == "hola" and nxt["remaining"] == 1
    reviewed = json.loads(_cli(home, "review", "1", "good", "--seconds", "4").stdout)
    assert reviewed["due_in"] == "10m"
    assert _cli(home, "next").stdout.strip() == "null"
    failed = _cli(home, "review", "1", "wrong")
    assert failed.returncode == 1 and failed.stdout == ""


def test_http_api_and_the_daemon_nudge(home: Path, serving: tuple[str, subprocess.Popen]):
    serving, serving_proc = serving
    created = _request(f"{serving}/cards", "POST", {"deck": "anatomy", "cards": [{"front": "femur", "back": "thigh bone"}]})
    assert created["added"] == 1
    assert _request(f"{serving}/next")["front"] == "femur"
    assert _request(f"{serving}/stats")["due_now"] == 1
    assert json.loads(_await_nudge(home, serving_proc).read_text())["due_count"] == 1
    reviewed = _request(f"{serving}/cards/1/review", "POST", {"rating": "good"})
    assert reviewed["state"] == "learning"
    assert _request(f"{serving}/config", "PATCH", {"name": "new_cards_per_day", "value": "3"})["new_cards_per_day"] == 3
    with pytest.raises(urllib.error.HTTPError) as failure:
        _request(f"{serving}/cards/1/review", "POST", {"rating": "wrong"})
    assert failure.value.code == 400


def test_http_api_serves_overlapping_requests(home: Path, serving: tuple[str, subprocess.Popen]):
    """A request's connection crosses threadpool threads, so overlapping requests must not trip sqlite's thread check."""
    serving, _ = serving
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        answers = list(pool.map(lambda _: _request(f"{serving}/stats")["cards"], range(64)))
    assert answers == [0] * 64


def test_daemon_start_without_the_api_clears_a_stale_port_record(home: Path):
    records = home / "agent/data/daemons"
    records.mkdir(parents=True)
    (records / "flashcards.port").write_text("4321")
    assert json.loads(_cli(home, "daemon", "start").stdout) == {"status": "started"}
    try:
        assert json.loads(_cli(home, "daemon", "status").stdout) == {"running": True, "port": None}
    finally:
        assert json.loads(_cli(home, "daemon", "stop").stdout) == {"status": "stopped"}


def test_serve_exits_when_the_api_port_is_taken(home: Path):
    with socket.socket() as taken:
        taken.bind(("", 0))
        taken.listen()
        proc = _serve(home, "--port", str(taken.getsockname()[1]))
        try:
            assert proc.wait(timeout=15) != 0
        finally:
            _end(proc)
    (died,) = (home / "agent/notifications").glob("*daemon_died.json")
    assert "http server" in json.loads(died.read_text())["reason"]


def test_daemon_start_reports_an_unreadable_store_as_an_error(tmp_path: Path):
    (tmp_path / ".flashcards" / "flashcards.db").mkdir(parents=True)
    result = _cli(tmp_path, "daemon", "start")
    assert result.returncode == 1 and result.stdout == ""
    assert "unable to open" in json.loads(result.stderr)["error"]
    assert not (tmp_path / "agent/data/daemons/flashcards.pid").exists()


def test_serve_without_a_port_nudges_and_serves_nothing(home: Path):
    assert _cli(home, "add", "--deck", "anatomy", "femur", "thigh bone").returncode == 0
    proc = _serve(home)
    try:
        assert json.loads(_await_nudge(home, proc).read_text())["due_count"] == 1
    finally:
        _end(proc)
