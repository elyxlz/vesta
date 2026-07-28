"""Exercises the REAL service-key script (the helper the agent runs to share a private
service) against a live HTTPS mock: `mint` must print the once-only secret and nothing
else, so `KEY=$(service-key mint ...)` composes into a link; the request must carry the
method, path, and JSON content type vestad's extractor requires; and a rejected request
must fail loudly on stderr instead of printing an empty key into a broken link."""

import http.server
import json
import pathlib as pl
import subprocess
import typing as tp

from https_stub import free_port, self_signed, serve_https

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "agent/skills/vestad/scripts/service-key"


class _Request(tp.NamedTuple):
    method: str
    path: str
    content_type: str | None
    agent_token: str | None
    body: str


class _KeyHandler(http.server.BaseHTTPRequestHandler):
    """Stands in for vestad's service-key routes, recording what the script sent."""

    status = 200
    mint_response = '{"id":"abc123","key":"deadbeef","expires_at":1800000000}'
    error_response = "{\"error\":\"service 'expenses' is not registered for agent 'test-agent'\"}"
    requests: tp.ClassVar[list[_Request]] = []

    def _record(self, method):
        length = self.headers["Content-Length"]
        body = self.rfile.read(int(length)).decode() if length is not None else ""
        self.requests.append(
            _Request(
                method=method,
                path=self.path,
                content_type=self.headers["Content-Type"],
                agent_token=self.headers["X-Agent-Token"],
                body=body,
            )
        )

    def _reply(self, payload):
        body = payload.encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self._record("POST")
        self._reply(self.mint_response if self.status == 200 else self.error_response)

    def do_GET(self):
        self._record("GET")
        self._reply('{"keys":[{"id":"abc123","label":"accountant"}]}' if self.status == 200 else self.error_response)

    def do_DELETE(self):
        self._record("DELETE")
        self._reply('{"status":"ok"}' if self.status == 200 else self.error_response)

    def log_message(self, *_args: object, **_kwargs: object) -> None:
        pass


def _run(args, tmp_path, status=200):
    """Runs the real script against the HTTPS stub, returning (result, recorded requests)."""
    cert, key = self_signed(tmp_path)
    port = free_port()
    _KeyHandler.requests.clear()
    _KeyHandler.status = status
    server = serve_https(port, cert, key, _KeyHandler)
    env = {
        "PATH": "/usr/bin:/bin",
        "BOX_HOST": "127.0.0.1",
        "VESTAD_PORT": str(port),
        "AGENT_NAME": "test-agent",
        "AGENT_TOKEN": "test-token",
        "HOME": str(tmp_path),
    }
    try:
        result = subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=30, check=False)
    finally:
        server.shutdown()
    return result, list(_KeyHandler.requests)


def _mint_body(args, tmp_path):
    result, requests = _run(["mint", *args], tmp_path)
    assert result.returncode == 0, result.stderr
    assert len(requests) == 1, requests
    return json.loads(requests[0].body)


def test_mint_prints_only_the_key(tmp_path):
    """The documented KEY=$(service-key mint ...) pattern puts stdout straight into a
    link, so a stray id, banner, or JSON wrapper would break the URL."""
    result, _ = _run(["mint", "expenses"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "deadbeef\n"


def test_mint_posts_json_to_the_service_keys_path(tmp_path):
    """vestad's JSON extractor 415s before the handler runs without the content type."""
    _, requests = _run(["mint", "expenses"], tmp_path)
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].path == "/agents/test-agent/services/expenses/keys"
    assert requests[0].content_type == "application/json"
    assert requests[0].agent_token == "test-token"


def test_mint_without_options_sends_an_empty_body(tmp_path):
    """No label and no ttl means vestad's own 30 day default decides the expiry."""
    assert _mint_body(["expenses"], tmp_path) == {}


def test_label_and_ttl_reach_the_body(tmp_path):
    assert _mint_body(["expenses", "--label", "accountant", "--ttl", "604800"], tmp_path) == {
        "label": "accountant",
        "ttl_secs": 604800,
    }


def test_never_expires_wins_over_ttl(tmp_path):
    """Matching the server, which ignores a ttl when never_expires is set."""
    assert _mint_body(["expenses", "--never-expires", "--ttl", "604800"], tmp_path) == {"never_expires": True}


def test_mint_fails_loudly_on_a_rejected_request(tmp_path):
    """A 404 (the service was never registered) must not print an empty key."""
    result, _ = _run(["mint", "expenses"], tmp_path, status=404)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "is not registered" in result.stderr
    assert "Traceback" not in result.stderr


def test_mint_fails_cleanly_when_vestad_is_unreachable(tmp_path):
    port = free_port()  # nothing listens here -> connection refused
    env = {
        "PATH": "/usr/bin:/bin",
        "BOX_HOST": "127.0.0.1",
        "VESTAD_PORT": str(port),
        "AGENT_NAME": "test-agent",
        "AGENT_TOKEN": "test-token",
        "HOME": str(tmp_path),
    }
    result = subprocess.run(["bash", str(SCRIPT), "mint", "expenses"], env=env, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "service-key:" in result.stderr
    assert "Traceback" not in result.stderr


def test_list_gets_the_keys_path_and_prints_the_body(tmp_path):
    result, requests = _run(["list", "expenses"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert requests[0].method == "GET"
    assert requests[0].path == "/agents/test-agent/services/expenses/keys"
    assert json.loads(result.stdout) == {"keys": [{"id": "abc123", "label": "accountant"}]}


def test_revoke_deletes_by_id_and_prints_nothing(tmp_path):
    result, requests = _run(["revoke", "expenses", "abc123"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert requests[0].method == "DELETE"
    assert requests[0].path == "/agents/test-agent/services/expenses/keys/abc123"


def test_revoke_of_an_unknown_id_fails(tmp_path):
    result, _ = _run(["revoke", "expenses", "nope"], tmp_path, status=404)
    assert result.returncode != 0
    assert "service-key:" in result.stderr
