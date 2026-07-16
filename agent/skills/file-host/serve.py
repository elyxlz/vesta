#!/usr/bin/env python3
"""Static file host: serve a directory over HTTP so files can be shared by link.

Pair with a public vestad service to get a shareable tunnel URL (see SKILL.md).
Stdlib only, no dependencies.

Usage:
  serve.py [--dir DIR] [--port N] [--no-cache]

  --dir       directory to serve (default ~/.file-host)
  --port      port to bind on 127.0.0.1 (default 8770)
  --no-cache  send Cache-Control: no-store on every response (use when serving
              a file that changes in place, e.g. a rotating QR image)
"""

import argparse
import http.server
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

    def end_headers(self):
        if args.no_cache:
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *fmt_args):
        print(self.client_address[0], fmt % fmt_args, flush=True)


class Server(socketserver.TCPServer):
    allow_reuse_address = True


with Server(("127.0.0.1", args.port), Handler) as httpd:
    print(f"file-host serving {serve_dir} on 127.0.0.1:{args.port} (no_cache={args.no_cache})", flush=True)
    httpd.serve_forever()
