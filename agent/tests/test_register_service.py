"""Exercises the REAL register-service script (the helper the restart skill's daemon
block runs) against a live HTTPS mock and an unreachable port: it must print the port
on success and, when vestad is down, fail cleanly (non-zero, empty stdout, a stderr
message, no Python traceback) instead of emitting an empty port that launches a
portless daemon (issue #960)."""

import http.server
import json
import pathlib as pl
import subprocess
import typing as tp

from https_stub import free_port, self_signed, serve_https

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "agent/skills/vestad/scripts/register-service"


def _run(port, tmp_path, wait="2", args=("tasks",)):
    env = {
        "PATH": "/usr/bin:/bin",
        "BOX_HOST": "127.0.0.1",
        "VESTAD_PORT": str(port),
        "AGENT_NAME": "test-agent",
        "AGENT_TOKEN": "test-token",
        "REGISTER_SERVICE_WAIT": wait,
        "HOME": str(tmp_path),
    }
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=30, check=False)


class _PortHandler(http.server.BaseHTTPRequestHandler):
    port_value = 45321
    posted_bodies: tp.ClassVar[list[str]] = []

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        self.posted_bodies.append(self.rfile.read(length).decode())
        body = f'{{"port":{self.port_value}}}'.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object, **_kwargs: object) -> None:
        pass


def _request_body(args, tmp_path):
    """Runs the real script against the HTTPS stub and returns the JSON body it POSTed."""
    cert, key = self_signed(tmp_path)
    port = free_port()
    _PortHandler.posted_bodies.clear()
    server = serve_https(port, cert, key, _PortHandler)
    try:
        result = _run(port, tmp_path, args=args)
    finally:
        server.shutdown()
    assert result.returncode == 0, result.stderr
    assert len(_PortHandler.posted_bodies) == 1, _PortHandler.posted_bodies
    return json.loads(_PortHandler.posted_bodies[0])


def test_prints_port_when_vestad_answers(tmp_path):
    cert, key = self_signed(tmp_path)
    port = free_port()
    server = serve_https(port, cert, key, _PortHandler)
    try:
        result = _run(port, tmp_path)
    finally:
        server.shutdown()
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "45321"


def test_fails_cleanly_when_vestad_unreachable(tmp_path):
    port = free_port()  # nothing listens here -> connection refused
    result = _run(port, tmp_path, wait="1")
    assert result.returncode != 0
    assert result.stdout.strip() == ""  # no empty/garbage port to launch a portless daemon
    assert "Traceback" not in result.stderr
    assert "JSONDecodeError" not in result.stderr
    assert "vestad unreachable" in result.stderr


def test_omitting_public_sends_an_explicit_false(tmp_path):
    """An omitted flag must not inherit a stale cached `public: true` on the box."""
    assert _request_body(["dashboard"], tmp_path) == {"name": "dashboard", "public": False}


def test_public_flag_sends_true(tmp_path):
    assert _request_body(["dashboard", "--public"], tmp_path) == {"name": "dashboard", "public": True}


def test_caller_and_chain_short_circuits_on_failure(tmp_path):
    """The documented `PORT=$(register-service ...) && start` pattern must not run
    the start command when registration fails."""
    port = free_port()
    env = {
        "PATH": "/usr/bin:/bin",
        "BOX_HOST": "127.0.0.1",
        "VESTAD_PORT": str(port),
        "AGENT_NAME": "test-agent",
        "AGENT_TOKEN": "test-token",
        "REGISTER_SERVICE_WAIT": "1",
        "HOME": str(tmp_path),
    }
    result = subprocess.run(
        ["bash", "-c", f'PORT=$("{SCRIPT}" tasks) && echo "STARTED:$PORT"'],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert "STARTED" not in result.stdout
