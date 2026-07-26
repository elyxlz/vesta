#!/usr/bin/env python3
"""Tiny browser-signature service. GET / serves a signature pad; POST /submit
receives the drawn signature PNG and saves it, then drops an interrupt
notification so the agent can stamp it onto the PDF. Stdlib only.

Run: python3 sign_server.py <PORT> [OUTPUT_PNG]
Default OUTPUT_PNG is /tmp/sign-service/signature.png.
"""

import base64
import datetime
import http.server
import json
import os
import socketserver
import sys
import traceback
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 49180
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/sign-service/signature.png")
DONE = OUT.parent / "SIGNED"
NOTIF_DIR = Path(os.environ.get("VESTA_NOTIF_DIR", "~/agent/notifications")).expanduser()

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign here</title>
<style>
 body{font-family:-apple-system,system-ui,sans-serif;max-width:640px;margin:32px auto;padding:0 16px;color:#111}
 h2{font-weight:600}
 #pad{border:2px dashed #bbb;border-radius:10px;background:#fff;touch-action:none;width:100%;height:220px;display:block}
 .row{margin-top:14px;display:flex;gap:10px}
 button{font-size:16px;padding:10px 18px;border-radius:8px;border:1px solid #ccc;background:#f5f5f5;cursor:pointer}
 #send{background:#111;color:#fff;border-color:#111}
 #ok{color:#137333;font-weight:600;margin-top:16px;display:none}
 p.hint{color:#666;font-size:14px}
</style></head><body>
<h2>Sign your name below</h2>
<p class="hint">Draw with your mouse or trackpad, then hit Submit. I will place it on your document.</p>
<canvas id="pad"></canvas>
<div class="row"><button id="clear">Clear</button><button id="send">Submit</button></div>
<div id="ok">Got it. You can close this tab.</div>
<script>
const c=document.getElementById('pad');const ctx=c.getContext('2d');
function fit(){
  const r=c.getBoundingClientRect();
  c.width=r.width*2;c.height=r.height*2;
  ctx.scale(2,2);ctx.lineWidth=2.2;ctx.lineCap='round';ctx.strokeStyle='#111';
}
fit();window.addEventListener('resize',fit);
let drawing=false,last=null;
function pos(e){const r=c.getBoundingClientRect();const t=e.touches?e.touches[0]:e;return{x:t.clientX-r.left,y:t.clientY-r.top};}
function start(e){drawing=true;last=pos(e);e.preventDefault();}
function move(e){
  if(!drawing)return;
  const p=pos(e);
  ctx.beginPath();ctx.moveTo(last.x,last.y);ctx.lineTo(p.x,p.y);ctx.stroke();
  last=p;e.preventDefault();
}
function end(){drawing=false;}
c.addEventListener('mousedown',start);c.addEventListener('mousemove',move);window.addEventListener('mouseup',end);
c.addEventListener('touchstart',start);c.addEventListener('touchmove',move);c.addEventListener('touchend',end);
document.getElementById('clear').onclick=()=>{ctx.clearRect(0,0,c.width,c.height);};
document.getElementById('send').onclick=async()=>{
 const data=c.toDataURL('image/png');
 const base=location.pathname.replace(/\\/?$/,'/');
 await fetch(base+'submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({signature:data})});
 document.getElementById('ok').style.display='block';
};
</script></body></html>"""


def _drop_notification():
    """Drop an interrupt notification so the agent stamps and previews the PDF."""
    NOTIF_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now().astimezone()
    nid = NOTIF_DIR / f"signature-received-{int(now.timestamp())}.json"
    nid.write_text(
        json.dumps(
            {
                "timestamp": now.isoformat(),
                "source": "sign-service",
                "type": "signature_received",
                "interrupt": True,
                "body": f"A signature was submitted at {OUT}. Run stamp.py to place it on the "
                "PDF, render the preview, show the user for approval, then deliver only on "
                "their explicit go-ahead.",
            }
        )
    )


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        print(self.client_address[0], fmt % a, flush=True)

    def do_GET(self):
        if not self.path.rstrip("/").endswith("submit"):
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        if not self.path.rstrip("/").endswith("submit"):
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        try:
            data = json.loads(raw)["signature"]
            b64 = data.split(",", 1)[1]
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_bytes(base64.b64decode(b64))
            DONE.write_text("1")
            try:
                _drop_notification()
            except Exception:
                traceback.print_exc()
            print("SIGNATURE RECEIVED ->", OUT, flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        except Exception as e:
            print("submit err:", e, flush=True)
            self.send_error(400)


class S(socketserver.TCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    with S(("127.0.0.1", PORT), H) as httpd:
        print(f"sign-service on 127.0.0.1:{PORT}", flush=True)
        httpd.serve_forever()
