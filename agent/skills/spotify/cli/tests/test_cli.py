"""The CLI's stream contract: success JSON on stdout, failure JSON on stderr with exit 1."""

import json
import sys

import pytest
from spotify_cli import cli


def _raise(*_args, **_kwargs):
    raise RuntimeError("boom")


def test_a_failing_command_prints_its_error_on_stderr_and_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(cli.search, "search", _raise)
    monkeypatch.setattr(sys, "argv", ["spotify", "search", "anything"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"error": "RuntimeError", "message": "boom"}


def test_a_successful_command_prints_its_result_on_stdout(monkeypatch, capsys):
    monkeypatch.setattr(cli.search, "search", lambda *_args, **_kwargs: {"tracks": []})
    monkeypatch.setattr(sys, "argv", ["spotify", "search", "anything"])

    cli.main()

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {"tracks": []}
