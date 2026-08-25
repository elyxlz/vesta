#!/usr/bin/env python3
"""One-shot web form that takes a secret from the user and writes it straight to the env file.

Every channel an agent has persists what the user types, in plaintext, indefinitely, so a
credential sent as a message is on disk the moment it arrives and stays there. This serves a single
form over the vestad tunnel instead: the user opens a link, types the value once, and it goes to
`~/.agent-secrets.env` without ever passing through a message store.

The value is never printed, logged, or echoed back. The server accepts exactly one submission and
then exits, and it exits anyway after the timeout, so an abandoned request does not leave a form
standing.
"""

import argparse
import http.server
import pathlib as pl
import re
import socketserver
import sys
import threading
import urllib.parse

SECRETS = pl.Path("~/.agent-secrets.env").expanduser()
NAME_OK = re.compile(r"^[A-Z][A-Z0-9_]*$")

PAGE = """<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Vesta</title>
<style>
 body{{background:#0e0e10;color:#e8e8ea;font:16px/1.5 system-ui,sans-serif;margin:0;
      display:grid;place-items:center;min-height:100vh}}
 form{{width:min(26rem,90vw);padding:2rem}}
 h1{{font-size:1.1rem;font-weight:600;margin:0 0 .25rem}}
 p{{color:#9b9ba1;font-size:.9rem;margin:0 0 1.5rem}}
 input{{width:100%;box-sizing:border-box;padding:.8rem;border-radius:.5rem;
        border:1px solid #303036;background:#17171a;color:#e8e8ea;font:inherit}}
 button{{width:100%;margin-top:.75rem;padding:.8rem;border:0;border-radius:.5rem;
         background:#e8e8ea;color:#0e0e10;font:inherit;font-weight:600}}
 .done{{text-align:center}}
</style>
<form method=post autocomplete=off>
 <h1>{label}</h1>
 <p>Paste it here rather than sending it in a message. It is written straight to the agent's
    environment and is not stored in any chat history.</p>
 <input name=value type=password autofocus required spellcheck=false>
 <button>Send</button>
</form>
"""

DONE = """<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Vesta</title>
<style>body{background:#0e0e10;color:#e8e8ea;font:16px/1.5 system-ui,sans-serif;margin:0;
 display:grid;place-items:center;min-height:100vh;text-align:center}</style>
<p>Saved. You can close this.</p>
"""


def write_secret(name: str, value: str) -> None:
    """Set name in the env file, replacing any existing definition rather than stacking a second."""
    SECRETS.touch(mode=0o600, exist_ok=True)
    SECRETS.chmod(0o600)
    keep = [ln for ln in SECRETS.read_text().splitlines() if not ln.startswith(f"export {name}=")]
    quoted = value.replace("'", "'\"'\"'")
    SECRETS.write_text("\n".join([*keep, f"export {name}='{quoted}'"]).strip() + "\n")


def ensure_sourced() -> None:
    """Make ~/.bashrc read the env file, so the value survives a restart like any other setting."""
    bashrc = pl.Path("~/.bashrc").expanduser()
    line = f"[ -f {SECRETS} ] && . {SECRETS}"
    body = bashrc.read_text() if bashrc.exists() else ""
    if line not in body:
        bashrc.write_text(body.rstrip("\n") + f"\n{line}\n")


def build(name: str, label: str, done: threading.Event) -> type:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            """Silence the access log: the default one would print the request line."""

        def _send(self, body: str, code: int = 200) -> None:
            raw = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            self._send(PAGE.format(label=label))

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 64_000:
                self._send(PAGE.format(label=label), 400)
                return
            field = urllib.parse.parse_qs(self.rfile.read(length).decode()).get("value", [""])
            value = field[0].strip()
            if not value:
                self._send(PAGE.format(label=label), 400)
                return
            write_secret(name, value)
            ensure_sourced()
            self._send(DONE)
            done.set()

    return Handler


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", help="env var to set, e.g. DOUBLETICK_API_KEY")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    if not NAME_OK.match(args.name):
        print(f"name must look like an env var, got {args.name!r}", file=sys.stderr)
        return 2

    done = threading.Event()
    socketserver.TCPServer.allow_reuse_address = True
    # Binds all interfaces because vestad runs on the host, outside this container, so it reaches
    # the port over the container network; 127.0.0.1 would be unreachable and the link would 502.
    # The gate is vestad's, which holds the service private behind a minted key.
    with socketserver.TCPServer(("0.0.0.0", args.port), build(args.name, args.label or args.name, done)) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print(f"listening on {args.port}, waiting up to {args.timeout}s", flush=True)
        if done.wait(args.timeout):
            # Names the variable that was set, never the value, and never interpolates the
            # SECRETS path: CodeQL's clear-text-logging rule treats an identifier matching
            # "secret" as a sensitive source, so naming the constant here trips it even though
            # a path is not a credential. The destination is documented in the module docstring.
            print(f"received: {args.name}, written to the env file")
            return 0
        print("timed out, nothing received", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
