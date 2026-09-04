"""Stand-ins for chromium and browser-use, written as executable scripts into a tmp bin dir."""

import pathlib as pl
import stat
import sys

FAKE_CHROMIUM = f"""#!{sys.executable}
import http.server, json, pathlib, sys, threading
args = sys.argv[1:]
profile = next(a.split("=", 1)[1] for a in args if a.startswith("--user-data-dir="))
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = {{"webSocketDebuggerUrl": "ws://127.0.0.1:%d/devtools/browser/x" % self.server.server_port}}
        if self.path == "/json/list":
            body = [{{"type": "page", "id": "T1", "url": "https://example.com/", "title": "Example Domain"}}]
        data = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
pathlib.Path(profile, "DevToolsActivePort").write_text(f"{{srv.server_port}}\\n/devtools/browser/x\\n")
srv.serve_forever()
"""

FAKE_BROWSER_USE = f"""#!{sys.executable}
import json, os, sys, time
code = sys.stdin.read()
if "SLEEP" in code:
    time.sleep(30)
if "FAIL" in code:
    print("boom", file=sys.stderr); sys.exit(1)
if "SHOT" in code:
    p = os.path.join(os.environ["BH_TMP_DIR"], "shot.png"); os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(b"\\x89PNG\\r\\n\\x1a\\n" + b"0" * 8); print(p)
print(json.dumps({{k: os.environ[k] for k in sorted(os.environ)}}))
"""


def write_fakes(bin_dir: pl.Path) -> dict[str, str]:
    bin_dir.mkdir(exist_ok=True)
    env = {}
    entries = (("chromium", FAKE_CHROMIUM, "VESTA_BROWSER_CHROMIUM"), ("browser-use", FAKE_BROWSER_USE, "VESTA_BROWSER_BROWSER_USE"))
    for name, body, key in entries:
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        env[key] = str(path)
    return env
