#!/usr/bin/env python3
"""Static file host: serve a directory over HTTP so files can be shared by link.

Pair with a public vestad service to get a shareable tunnel URL (see SKILL.md).
Stdlib only, no dependencies.

Usage:
  serve.py [--dir DIR] [--port N] [--no-cache]

  --dir       directory to serve (default ~/.file-host)
  --port      port to bind on 0.0.0.0 (default 8770)
  --no-cache  send Cache-Control: no-store on every response (use when serving
              a file that changes in place, e.g. a rotating QR image)
"""

import argparse
import http.server
import re
import socketserver
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--dir", default=str(Path("~/.file-host").expanduser()))
parser.add_argument("--port", type=int, default=8770)
parser.add_argument("--no-cache", action="store_true")
args = parser.parse_args()

serve_dir = str(Path(args.dir).expanduser().resolve())
Path(serve_dir).mkdir(parents=True, exist_ok=True)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *handler_args, **handler_kwargs):
        super().__init__(*handler_args, directory=serve_dir, **handler_kwargs)

    def send_head(self):
        # Serve a single byte range: iOS/Safari media players will not play a file without 206 support.
        path = Path(self.translate_path(self.path))
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if not m or not any(m.groups()) or not path.is_file():
            return super().send_head()
        size = path.stat().st_size
        first, last = m.groups()
        start = int(first) if first else max(0, size - int(last))
        end = min(int(last), size - 1) if first and last else size - 1
        if start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        if self.command == "GET":
            with path.open("rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0 and (chunk := f.read(min(65536, left))):
                    self.wfile.write(chunk)
                    left -= len(chunk)
        return None

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        if args.no_cache:
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *fmt_args):
        print(self.client_address[0], fmt % fmt_args, flush=True)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


with Server(("0.0.0.0", args.port), Handler) as httpd:
    print(f"file-host serving {serve_dir} on 0.0.0.0:{args.port} (no_cache={args.no_cache})", flush=True)
    httpd.serve_forever()
