import io
import json
import socket
import subprocess
import sys
import threading
import time

import pytest
from vesta_browser import cli, serve
from vesta_browser.runtime_paths import load_paths


def test_daemon_down_is_a_loud_error_on_stderr(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(sys, "stdin", io.StringIO("print(1)"))
    code = cli.main(["exec", "--session", "default"])
    out, err = capsys.readouterr()
    assert code == 1 and out == ""
    envelope = json.loads(err)
    assert envelope["ok"] is False and envelope["error"]["code"] == "daemon_down"
    assert envelope["error"]["suggested_action"] == "run: browser daemon start"


def test_daemon_closing_without_an_answer_is_also_daemon_down(tmp_path, monkeypatch, capsys):
    """A crashed daemon, or `daemon stop` racing an in-flight request, closes the socket having
    written nothing; that must read as `daemon_down`, not a raw json.JSONDecodeError traceback."""
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = load_paths({}, tmp_path)
    paths.root.mkdir(parents=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(paths.socket))
    server.listen(1)

    def stub():
        conn, _ = server.accept()
        conn.makefile("rb").readline()
        conn.close()

    threading.Thread(target=stub, daemon=True).start()
    monkeypatch.setattr(sys, "stdin", io.StringIO("print(1)"))
    code = cli.main(["exec"])
    out, err = capsys.readouterr()
    assert code == 1 and out == ""
    envelope = json.loads(err)
    assert envelope["ok"] is False and envelope["error"]["code"] == "daemon_down"


def test_exec_sends_the_request_and_prints_one_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    seen = {}

    def fake_send(_paths, payload, timeout):
        seen.update(payload)
        return serve.p.result(request_id=payload["request_id"], op="exec", ok=True, data={"echo": True})

    monkeypatch.setattr(cli, "send", fake_send)
    monkeypatch.setattr(sys, "stdin", io.StringIO("new_tab('x')\n"))
    code = cli.main(["exec", "--session", "research", "--stealth", "--timeout", "42"])
    out, err = capsys.readouterr()
    assert code == 0 and err == "" and out.count("\n") == 1
    assert seen["op"] == "exec" and seen["session"] == "research" and seen["mode"] == "stealth"
    assert seen["timeout_s"] == 42 and seen["code"] == "new_tab('x')\n" and seen["version"] == 1


def test_exec_without_stealth_sends_a_null_mode(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    seen = {}
    monkeypatch.setattr(cli, "send", lambda _p, payload, _t: seen.update(payload) or serve.p.result(request_id="x", op="exec", ok=True))
    monkeypatch.setattr(sys, "stdin", io.StringIO("print(1)"))
    cli.main(["exec"])
    assert seen["mode"] is None and seen["session"] == "default" and seen["timeout_s"] == 120


def test_failed_result_goes_to_stderr_with_exit_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    err = serve.p.error("execution_failed", "execution", "boom", retryable=False, suggested_action="fix")
    monkeypatch.setattr(cli, "send", lambda _p, payload, _t: serve.p.result(request_id="x", op="exec", ok=False, err=err))
    monkeypatch.setattr(sys, "stdin", io.StringIO("print(1)"))
    code = cli.main(["exec"])
    out, stderr = capsys.readouterr()
    assert code == 1 and out == "" and json.loads(stderr)["error"]["code"] == "execution_failed"


@pytest.mark.parametrize(
    ("argv", "op", "extra"),
    [
        (["doctor"], "doctor", {}),
        (["engines"], "engines", {}),
        (["sessions"], "sessions", {}),
        (["session", "stop", "research"], "session_stop", {"session": "research"}),
        (["stop-all"], "stop_all", {}),
        (
            ["handover", "start", "--url", "https://x", "--session", "s", "--stealth", "--minutes", "10"],
            "handover_start",
            {"url": "https://x", "session": "s", "mode": "stealth", "minutes": 10},
        ),
        (["handover", "status"], "handover_status", {}),
        (["handover", "stop"], "handover_stop", {}),
    ],
)
def test_every_rpc_command_maps_to_its_op(monkeypatch, tmp_path, argv, op, extra):
    monkeypatch.setenv("HOME", str(tmp_path))
    seen = {}
    monkeypatch.setattr(cli, "send", lambda _p, payload, _t: seen.update(payload) or serve.p.result(request_id="x", op=op, ok=True))
    assert cli.main(argv) == 0
    assert seen["op"] == op and all(seen[k] == v for k, v in extra.items())


def test_usage_on_no_args_and_unknown_command(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cli.main([]) == 0
    out, err = capsys.readouterr()
    assert "usage" in out.lower() and err == ""
    assert cli.main(["help"]) == 0
    out, err = capsys.readouterr()
    assert "usage" in out.lower() and err == ""
    assert cli.main(["dance"]) == 1
    out, err = capsys.readouterr()
    assert out == "" and "usage" in err.lower()


def test_sigint_during_exec_sends_cancel(tmp_path, monkeypatch):
    """Runs the real CLI as a subprocess against a stub daemon that holds the exec until it sees cancel."""
    paths = load_paths({}, tmp_path)
    paths.root.mkdir(parents=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(paths.socket))
    server.listen(2)
    seen_ops = []

    def stub():
        first, _ = server.accept()
        first_req = json.loads(first.makefile("rb").readline())
        seen_ops.append(first_req["op"])
        second, _ = server.accept()
        second_req = json.loads(second.makefile("rb").readline())
        seen_ops.append(second_req["op"])
        second.sendall(json.dumps(serve.p.result(request_id="c", op="cancel", ok=True)).encode() + b"\n")
        second.close()
        first.sendall(json.dumps(serve.p.result(request_id=first_req["request_id"], op="exec", ok=False)).encode() + b"\n")
        first.close()

    threading.Thread(target=stub, daemon=True).start()
    proc = subprocess.Popen(
        [sys.executable, "-c", "import sys; from vesta_browser.cli import main; sys.exit(main(['exec']))"],
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(cli.__file__).rsplit("/vesta_browser", 1)[0]},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    proc.stdin.write("SLEEP")
    proc.stdin.close()
    # The CLI installs its SIGINT handler before it sends, so the stub seeing the exec request is
    # the signal that interrupting it now reaches that handler.
    deadline = time.monotonic() + 10
    while not seen_ops and time.monotonic() < deadline:
        time.sleep(0.02)
    assert seen_ops == ["exec"]
    proc.send_signal(2)
    # Not proc.communicate(): CPython's communicate() unconditionally reflushes stdin and only
    # catches BrokenPipeError, so a stdin already closed above raises ValueError on 3.12. wait()
    # plus a direct stderr read sidesteps the double-close with no risk of a pipe deadlock, since
    # this process's own stderr is one short JSON line.
    proc.wait(timeout=10)
    err = proc.stderr.read()
    assert proc.returncode == 1 and seen_ops == ["exec", "cancel"]
    assert json.loads(err)["error"]["code"] == "cancelled"
