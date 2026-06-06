#!/usr/bin/env python3
"""Self-contained QR link page for WhatsApp device linking.

Serves a tiny auto-refreshing web page that always shows the CURRENT QR code,
so the user never scans a stale/cached one (WhatsApp rotates the QR every ~20s
and browsers cache a static image by URL). Stdlib only, no dependencies.

Flow:
  1. Start the daemon for the instance you are linking (so it writes qr-code.png).
  2. Run this server, then expose its port to the user (on vesta: register a
     public service and hand them the tunnel URL; otherwise any tunnel/ssh).
  3. User opens the page on a second screen, goes to WhatsApp > Settings >
     Linked Devices > Link a Device, and scans. The page self-refreshes, so
     they just leave it open and scan whatever code is showing.

Usage:
  qr-link-server.py [--instance NAME] [--port N]

Notes:
  - QR served with Cache-Control: no-store so refresh always re-fetches.
  - If WhatsApp shows "couldn't link", the daemon WS went stale: restart the
    daemon (re-arms the QR loop), the page picks up the new code automatically.
"""

import argparse
import http.server
import os
import socketserver

parser = argparse.ArgumentParser()
parser.add_argument("--instance", default="", help="instance name (blank = default)")
parser.add_argument("--port", type=int, default=8799)
args = parser.parse_args()

base = os.path.expanduser("~/.whatsapp")
qr_path = os.path.join(base, args.instance, "qr-code.png") if args.instance else os.path.join(base, "qr-code.png")

PAGE = b"""<!doctype html><html><head><meta charset="utf-8"><title>Link WhatsApp</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{background:#111;color:#eee;font-family:sans-serif;text-align:center;padding:24px}
img{width:300px;height:300px;background:#fff;padding:12px;border-radius:8px}
p{opacity:.7;font-size:14px;max-width:360px;margin:16px auto}</style></head>
<body><h3>Link WhatsApp</h3><img id="q" src="/qr.png" alt="QR code">
<p>On your phone: WhatsApp &gt; Settings &gt; Linked Devices &gt; Link a Device, then scan. This refreshes every 3s, just leave it open and scan the current code.</p>
<script>setInterval(function(){document.getElementById('q').src='/qr.png?t='+Date.now();},3000);</script>
</body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/qr.png"):
            if os.path.exists(qr_path):
                with open(qr_path, "rb") as handle:
                    data = handle.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)

    def log_message(self, *_args):
        pass


class Server(socketserver.TCPServer):
    allow_reuse_address = True


with Server(("127.0.0.1", args.port), Handler) as httpd:
    print(f"QR link page on http://127.0.0.1:{args.port} (instance={args.instance or 'default'}, qr={qr_path})", flush=True)
    httpd.serve_forever()
