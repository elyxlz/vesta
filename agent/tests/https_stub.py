"""Shared HTTPS stub for the vestad-script tests: a free port, a self-signed cert, and a
threaded TLS server around whatever handler class a suite supplies."""

import http.server
import pathlib as pl
import socket
import ssl
import subprocess
import threading


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def self_signed(tmp_path: pl.Path) -> tuple[pl.Path, pl.Path]:
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


def serve_https(port: int, cert: pl.Path, key: pl.Path, handler: type[http.server.BaseHTTPRequestHandler]) -> http.server.HTTPServer:
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # Pin the floor so the stub cannot negotiate TLS 1.0 or 1.1, which the default
    # context still permits and which code scanning flags as an insecure protocol.
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(cert), str(key))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
