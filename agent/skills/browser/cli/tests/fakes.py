"""Stand-ins for chromium and browser-use, written as executable scripts into a tmp bin dir."""

import pathlib as pl
import stat
import sys

FAKE_CHROMIUM = f"""#!{sys.executable}
import http.server, json, os, pathlib, sys, threading
args = sys.argv[1:]
profile = next(a.split("=", 1)[1] for a in args if a.startswith("--user-data-dir="))
pathlib.Path(profile, "fake.pid").write_text(str(os.getpid()))
with open(os.path.join(profile, "launches"), "a") as f:
    f.write(str(os.getpid()) + "\\n")
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = {{"webSocketDebuggerUrl": "ws://127.0.0.1:%d/devtools/browser/x" % self.server.server_port}}
        if self.path == "/json/list":
            entry = {{"type": "page", "id": "T1", "url": "https://example.com/"}}
            if not pathlib.Path(profile, "malformed-list").exists():
                entry["title"] = "Example Domain"
            body = [entry]
        data = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
if not pathlib.Path(profile, "no-port").exists():
    pathlib.Path(profile, "DevToolsActivePort").write_text(f"{{srv.server_port}}\\n/devtools/browser/x\\n")
srv.serve_forever()
"""

FAKE_BROWSER_USE = f"""#!{sys.executable}
import json, os, pathlib, sys, time
pathlib.Path(os.environ["BH_TMP_DIR"], "exec.pid").write_text(str(os.getpid()))
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


# The display stack's four binaries. Each fake bakes the X socket dir in at write time, because the
# real launches hand every child a closed env (PATH, HOME, DISPLAY, MOZ_ENABLE_WAYLAND) that no
# test variable can ride into. X11_DIR is that hole.
X11_DIR = "@@X11_DIR@@"

FAKE_XVFB = f"""#!{sys.executable}
import os, pathlib, socket, sys, time
number = next(a[1:] for a in sys.argv[1:] if a.startswith(":")).split(".")[0]
x11 = pathlib.Path("{X11_DIR}")
x11.mkdir(parents=True, exist_ok=True)
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.bind(str(x11 / ("X" + number)))
sock.listen(8)
(x11 / ("xvfb-" + number + ".pid")).write_text(str(os.getpid()))
time.sleep(3600)
"""

FAKE_OPENBOX = f"""#!{sys.executable}
import time
time.sleep(3600)
"""

FAKE_X11VNC = f"""#!{sys.executable}
import pathlib, socket, sys, time
port = int(sys.argv[sys.argv.index("-rfbport") + 1])
if pathlib.Path("{X11_DIR}", "fail-always").exists():
    sys.exit(1)
if pathlib.Path("{X11_DIR}", "fail-shm").exists() and "-noshm" not in sys.argv:
    sys.exit(1)
sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", port))
sock.listen(8)
time.sleep(3600)
"""

FAKE_WEBSOCKIFY = f"""#!{sys.executable}
import functools, http.server, sys
web = sys.argv[sys.argv.index("--web") + 1]
port = int(sys.argv[-2].rsplit(":", 1)[1])
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=web)
http.server.HTTPServer(("127.0.0.1", port), handler).serve_forever()
"""


def write_display_fakes(bin_dir: pl.Path, x11_dir: pl.Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    x11_dir.mkdir(parents=True, exist_ok=True)
    entries = (("Xvfb", FAKE_XVFB), ("openbox", FAKE_OPENBOX), ("x11vnc", FAKE_X11VNC), ("websockify", FAKE_WEBSOCKIFY))
    for name, body in entries:
        path = bin_dir / name
        path.write_text(body.replace(X11_DIR, str(x11_dir)))
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
