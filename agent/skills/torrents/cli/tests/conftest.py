"""A real in-process qBittorrent WebUI fake: an HTTP server that records every request and
serves configurable torrent lists, so qb tests exercise the real transport code end to end."""

import http.server
import json
import threading
import urllib.parse

import pytest


class FakeQb:
    def __init__(self) -> None:
        self.torrents: list[dict[str, object]] = []
        self.removed_endpoints: set[str] = set()
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.raw_bodies: list[bytes] = []

        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _respond(self, method: str) -> None:
                path = urllib.parse.urlparse(self.path).path.removeprefix("/api/v2/")
                length = int(self.headers["Content-Length"]) if "Content-Length" in self.headers else 0
                body = self.rfile.read(length)
                fake.raw_bodies.append(body)
                fields = dict(urllib.parse.parse_qsl(body.decode(errors="replace")))
                fake.requests.append((method, path, fields))
                if path in fake.removed_endpoints:
                    self.send_error(404)
                    return
                payload = json.dumps(fake.torrents).encode() if path == "torrents/info" else b"Ok."
                if path == "app/preferences":
                    payload = json.dumps({"max_ratio": 1.0, "max_seeding_time": 11520, "max_ratio_act": 0}).encode()
                if path == "sync/maindata":
                    payload = json.dumps({"server_state": {"free_space_on_disk": 5_000_000_000}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self) -> None:
                self._respond("GET")

            def do_POST(self) -> None:
                self._respond("POST")

            def log_message(self, fmt: str, *args: object) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def paths(self) -> list[str]:
        return [path for _, path, _ in self.requests]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake_qb(monkeypatch: pytest.MonkeyPatch):
    fake = FakeQb()
    monkeypatch.delenv("MEDIA_SERVER_HOST", raising=False)
    monkeypatch.setenv("QB_HOST", "127.0.0.1")
    monkeypatch.setenv("QB_PORT", str(fake.port))
    yield fake
    fake.close()
