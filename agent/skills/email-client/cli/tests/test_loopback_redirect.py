"""The loopback OAuth listener must capture the redirect even while an idle socket is open.

Chromium opens speculative preconnect sockets to the redirect origin and leaves them idle;
a single-threaded server blocks reading one and never handles the ?code= request.
"""

import http.client
import socket
import time

from email_client import auth


def test_redirect_is_captured_while_an_idle_connection_is_open(monkeypatch):
    monkeypatch.setattr(auth._RedirectHandler, "captured", None)
    port = auth._free_port()
    server = auth._start_redirect_server(port)
    idle = socket.create_connection(("127.0.0.1", port))
    try:
        time.sleep(0.2)  # let the server accept the idle socket first
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/?code=x&state=st")
        assert conn.getresponse().status == 200
        conn.close()
        assert auth._RedirectHandler.captured == {"code": "x", "state": "st", "error": None}
    finally:
        idle.close()
        server.shutdown()
        server.server_close()


def test_requests_without_code_are_ignored(monkeypatch):
    monkeypatch.setattr(auth._RedirectHandler, "captured", None)
    port = auth._free_port()
    server = auth._start_redirect_server(port)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/favicon.ico")
        assert conn.getresponse().status == 204
        conn.close()
        assert auth._RedirectHandler.captured is None
    finally:
        server.shutdown()
        server.server_close()
