"""The microsoft daemon subcommand delegates to the shared runner, and a deliberate stop is
distinguishable from a crash so it does not fire a false daemon_died notification."""

import json

from microsoft_cli import cli
from microsoft_cli.config import Config


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


def test_daemon_lifecycle_args_declare_a_portless_session(tmp_path):
    config = Config(data_dir=tmp_path / ".microsoft", log_dir=tmp_path / ".microsoft/logs")
    args = cli.daemon_lifecycle_args("start", config)

    assert args[1] == "start"
    assert args[args.index("--session") + 1] == "microsoft"
    assert "--port-mode" not in args
    assert args[args.index("--stop-marker") + 1] == str(tmp_path / ".microsoft/stop-requested")
    assert args[args.index("--") + 1 : args.index("--") + 3] == ["microsoft", "serve"]
