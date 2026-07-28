from pathlib import Path

from tasks_cli import cli


def test_serve_notifications_dir_defaults_to_agent_notifications(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    captured: dict[str, Path] = {}

    def fake_run_serve(config, notif_dir, *, port):
        captured["notif_dir"] = notif_dir

    monkeypatch.setattr(cli, "_run_serve", fake_run_serve)
    monkeypatch.setattr("sys.argv", ["tasks", "serve", "--port", "1"])
    cli.main()

    assert captured["notif_dir"] == tmp_path / "agent" / "notifications"
