"""Exercises the REAL register-service script (the helper the restart skill's daemon
block runs) against a live HTTPS mock and an unreachable port: it must print the port
on success and, when vestad is down, fail cleanly (non-zero, empty stdout, a stderr
message, no Python traceback) instead of emitting an empty port that launches a
portless daemon (issue #960)."""

import http.server
import pathlib as pl
import socket
import ssl
import subprocess
import threading

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "agent/skills/service/scripts/register-service"


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _self_signed(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


def _run(port, tmp_path, wait="2"):
    env = {
        "PATH": "/usr/bin:/bin",
        "VESTAD_PORT": str(port),
        "AGENT_NAME": "test-agent",
        "AGENT_TOKEN": "test-token",
        "REGISTER_SERVICE_WAIT": wait,
        "HOME": str(tmp_path),
    }
    return subprocess.run(["bash", str(SCRIPT), "tasks"], env=env, capture_output=True, text=True, timeout=30)


class _PortHandler(http.server.BaseHTTPRequestHandler):
    port_value = 45321

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        self.rfile.read(length)
        body = f'{{"port":{self.port_value}}}'.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _serve_https(port, cert, key):
    server = http.server.HTTPServer(("127.0.0.1", port), _PortHandler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_prints_port_when_vestad_answers(tmp_path):
    cert, key = _self_signed(tmp_path)
    port = _free_port()
    server = _serve_https(port, cert, key)
    try:
        result = _run(port, tmp_path)
    finally:
        server.shutdown()
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "45321"


def test_fails_cleanly_when_vestad_unreachable(tmp_path):
    port = _free_port()  # nothing listens here -> connection refused
    result = _run(port, tmp_path, wait="1")
    assert result.returncode != 0
    assert result.stdout.strip() == ""  # no empty/garbage port to launch a portless daemon
    assert "Traceback" not in result.stderr
    assert "JSONDecodeError" not in result.stderr
    assert "vestad unreachable" in result.stderr


def test_caller_and_chain_short_circuits_on_failure(tmp_path):
    """The documented `PORT=$(register-service ...) && start` pattern must not run
    the start command when registration fails."""
    port = _free_port()
    env = {
        "PATH": "/usr/bin:/bin",
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
    )
    assert "STARTED" not in result.stdout
