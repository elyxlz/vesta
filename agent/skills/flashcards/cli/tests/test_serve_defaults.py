from pathlib import Path

from flashcards_cli import cli


def _serve(home: Path, monkeypatch, *argv: str) -> dict[str, Path | int | None]:
    captured: dict[str, Path | int | None] = {}

    def fake_run_serve(config, notif_dir, *, port):
        captured["notif_dir"] = notif_dir
        captured["port"] = port

    monkeypatch.setattr(cli, "_run_serve", fake_run_serve)
    monkeypatch.setattr("sys.argv", ["flashcards", "serve", *argv])
    cli.main()
    return captured


def test_serve_notifications_dir_defaults_to_agent_notifications(home, monkeypatch):
    captured = _serve(home, monkeypatch, "--port", "1")
    assert captured == {"notif_dir": home / "agent" / "notifications", "port": 1}


def test_serve_without_a_port_runs_the_nudger_alone(home, monkeypatch):
    assert _serve(home, monkeypatch)["port"] is None
