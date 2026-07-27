"""The tasks daemon subcommand delegates to the shared runner, and a deliberate stop is
distinguishable from a crash so it does not fire a false daemon_died notification."""

import json
import pathlib as pl

from tasks_cli import cli
from tasks_cli.config import Config


def test_stop_marker_suppresses_and_clears(tmp_path):
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    marker = tmp_path / "stop-requested"
    marker.write_text("")

    cli.emit_daemon_died(notif_dir, reason="SIGTERM", stop_marker=marker)

    assert list(notif_dir.iterdir()) == []
    assert not marker.exists()


def test_unmarked_exit_writes_daemon_died(tmp_path):
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    marker = tmp_path / "stop-requested"

    cli.emit_daemon_died(notif_dir, reason="SIGKILL", stop_marker=marker)

    written = list(notif_dir.iterdir())
    assert len(written) == 1
    assert json.loads(written[0].read_text())["type"] == "daemon_died"


def test_stop_marker_lives_in_the_data_dir(tmp_path):
    config = Config(data_dir=tmp_path / ".tasks", log_dir=tmp_path / ".tasks/logs")
    assert cli.stop_marker_path(config) == tmp_path / ".tasks/stop-requested"


def test_daemon_lifecycle_args_declare_session_service_and_port(tmp_path):
    config = Config(data_dir=tmp_path / ".tasks", log_dir=tmp_path / ".tasks/logs")
    args = cli.daemon_lifecycle_args("start", config)

    assert args[0] == str(pl.Path.home() / "agent/skills/vestad/scripts/daemon-lifecycle")
    assert args[1] == "start"
    assert "--session" in args and args[args.index("--session") + 1] == "tasks"
    assert "--service" in args and args[args.index("--service") + 1] == "tasks"
    assert args[args.index("--port-mode") + 1] == "private"
    assert args[args.index("--stop-marker") + 1] == str(tmp_path / ".tasks/stop-requested")
    assert args[args.index("--") + 1 :] == ["tasks", "serve", "--port", "$PORT"]
