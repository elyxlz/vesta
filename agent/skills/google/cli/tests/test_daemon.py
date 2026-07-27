"""A deliberate stop is never reported as a crash: the shared runner's stop marker suppresses the
daemon_died notification and is consumed, while an unmarked exit announces itself."""

import json
from pathlib import Path

from google_cli import cli
from google_cli.config import Config


def _notifications(notif_dir: Path) -> list[Path]:
    return sorted(notif_dir.glob("*.json"))


def test_a_marked_shutdown_stays_silent_and_consumes_the_marker(tmp_path):
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    marker = tmp_path / "stop-requested"
    marker.write_text("")

    cli.emit_daemon_died(notif_dir, reason="SIGTERM", stop_marker=marker)

    assert _notifications(notif_dir) == []
    assert not marker.exists()


def test_an_unmarked_shutdown_announces_the_death_with_its_reason(tmp_path):
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()

    cli.emit_daemon_died(notif_dir, reason="SIGKILL", stop_marker=tmp_path / "stop-requested")

    written = _notifications(notif_dir)
    assert len(written) == 1
    notif = json.loads(written[0].read_text())
    assert notif["source"] == "google"
    assert notif["type"] == "daemon_died"
    assert notif["reason"] == "SIGKILL"


def test_a_crash_after_a_consumed_marker_is_still_announced(tmp_path):
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    marker = tmp_path / "stop-requested"
    marker.write_text("")

    cli.emit_daemon_died(notif_dir, reason="SIGTERM", stop_marker=marker)
    cli.emit_daemon_died(notif_dir, reason="crashed", stop_marker=marker)

    written = _notifications(notif_dir)
    assert len(written) == 1
    assert json.loads(written[0].read_text())["reason"] == "crashed"


def test_the_runner_is_told_the_marker_the_daemon_looks_for(tmp_path):
    config = Config(data_dir=tmp_path / ".google", log_dir=tmp_path / ".google" / "logs")

    args = cli.daemon_lifecycle_args("start", config)

    assert args[args.index("--stop-marker") + 1] == str(tmp_path / ".google" / "stop-requested")
    assert cli.stop_marker_path(config) == tmp_path / ".google" / "stop-requested"
