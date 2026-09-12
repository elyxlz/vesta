import json
from pathlib import Path

import pytest
from flashcards_cli import cli


def _main(monkeypatch, capsys, *argv):
    monkeypatch.setattr("sys.argv", ["flashcards", *argv])
    code = 0
    try:
        cli.main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    out, err = capsys.readouterr()
    return code, out, err


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_help_forms_print_usage_on_stdout_and_exit_zero(home, monkeypatch, capsys):
    for argv in ((), ("help",), ("--help",), ("daemon", "help")):
        code, out, err = _main(monkeypatch, capsys, *argv)
        assert code == 0 and "flashcards" in out and err == ""


def test_success_is_one_json_line_on_stdout_and_failure_one_envelope_on_stderr(home, monkeypatch, capsys):
    code, out, err = _main(monkeypatch, capsys, "add", "--deck", "spanish", "hola", "hello")
    assert code == 0 and err == "" and out.count("\n") == 1
    assert json.loads(out)["added"] == 1
    code, out, err = _main(monkeypatch, capsys, "review", "1", "good")
    assert code == 0 and json.loads(out)["state"] == "learning"
    code, out, err = _main(monkeypatch, capsys, "review", "7", "good")
    assert code == 1 and out == "" and json.loads(err) == {"error": "no card with id 7"}
    assert (home / ".flashcards" / "flashcards.db").exists()


def test_add_from_a_file_and_stdin(home, monkeypatch, capsys, tmp_path):
    cards = Path(tmp_path / "cards.json")
    cards.write_text(json.dumps([{"front": "a", "back": "1"}, {"front": "b", "back": "2", "notes": "n"}]))
    code, out, _ = _main(monkeypatch, capsys, "add", "--deck", "d", "--file", str(cards))
    assert code == 0 and json.loads(out)["added"] == 2
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps([{"front": "c", "back": "3"}])))
    code, out, _ = _main(monkeypatch, capsys, "add", "--deck", "d", "--file", "-")
    assert code == 0 and json.loads(out)["ids"] == [3]
    cards.write_text(json.dumps([{"front": "only"}]))
    code, _, err = _main(monkeypatch, capsys, "add", "--deck", "d", "--file", str(cards))
    assert code == 1 and "front and a back" in json.loads(err)["error"]


def test_tables_by_default_and_json_on_request(home, monkeypatch, capsys):
    _main(monkeypatch, capsys, "add", "--deck", "spanish", "hola", "hello")
    code, out, _ = _main(monkeypatch, capsys, "due")
    assert code == 0 and out.splitlines()[0].split() == ["id", "deck", "state", "due", "front"]
    code, out, _ = _main(monkeypatch, capsys, "due", "--json")
    assert json.loads(out)[0]["front"] == "hola"
    code, out, _ = _main(monkeypatch, capsys, "deck", "list", "--json-pretty")
    assert out.count("\n") > 1 and json.loads(out)[0]["name"] == "spanish"


def test_config_shows_and_sets_values(home, monkeypatch, capsys):
    code, out, _ = _main(monkeypatch, capsys, "config")
    assert code == 0 and json.loads(out)["desired_retention"] == 0.9
    code, out, _ = _main(monkeypatch, capsys, "config", "active_hours", "08:00-23:00")
    assert code == 0 and json.loads(out)["active_hours"] == "08:00-23:00"
    code, _, err = _main(monkeypatch, capsys, "config", "desired_retention")
    assert code == 1 and "needs a value" in json.loads(err)["error"]
    code, out, _ = _main(monkeypatch, capsys, "config", "api_enabled", "on")
    assert code == 0 and json.loads(out)["api_enabled"] is True
    code, _, err = _main(monkeypatch, capsys, "config", "api_enabled", "maybe")
    assert code == 1 and json.loads(err)["error"] == "api_enabled must be true or false"
