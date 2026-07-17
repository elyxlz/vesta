"""`tasks daemon status` reports real serving liveness, not mere presence.

The check curls the daemon's own HTTP port: a live sqlite store or a live screen
session proves neither. These pin the contract proactive-check relies on: exit 0 /
running:true only when the port actually answers.
"""

import json
import socket
from contextlib import contextmanager

import pytest
from tasks_cli import cli
from tasks_cli.config import Config


def _read_status(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip())


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_status_down_when_no_port_file(tmp_config: Config, capsys):
    with pytest.raises(SystemExit) as exc:
        cli._daemon_status(tmp_config, quiet=False)
    assert exc.value.code == 1
    assert _read_status(capsys)["running"] is False


def test_status_down_when_port_refused(tmp_config: Config, capsys):
    (tmp_config.data_dir / "serve.port").write_text(str(_free_port()))
    with pytest.raises(SystemExit) as exc:
        cli._daemon_status(tmp_config, quiet=False)
    assert exc.value.code == 1
    assert _read_status(capsys)["running"] is False


def test_status_up_when_port_serves(tmp_config: Config, monkeypatch, capsys):
    port = _free_port()
    (tmp_config.data_dir / "serve.port").write_text(str(port))

    class _Resp:
        status = 200

    @contextmanager
    def fake_urlopen(url, timeout):
        assert url == f"http://127.0.0.1:{port}/tasks"
        yield _Resp()

    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(SystemExit) as exc:
        cli._daemon_status(tmp_config, quiet=False)
    assert exc.value.code == 0
    status = _read_status(capsys)
    assert status["running"] is True
    assert status["port"] == port


def test_status_quiet_suppresses_output(tmp_config: Config, capsys):
    with pytest.raises(SystemExit) as exc:
        cli._daemon_status(tmp_config, quiet=True)
    assert exc.value.code == 1
    assert capsys.readouterr().out == ""


def test_daemon_status_routes_through_cli(tmp_config: Config, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Config", lambda: tmp_config)
    monkeypatch.setattr("sys.argv", ["tasks", "daemon", "status"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert _read_status(capsys)["running"] is False
