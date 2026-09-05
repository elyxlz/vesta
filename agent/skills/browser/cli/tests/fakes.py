"""Stand-ins for chromium and browser-use, written as executable scripts into a tmp bin dir."""

import pathlib as pl
import stat
import sys

FAKE_CHROMIUM = f"""#!{sys.executable}
import http.server, json, os, pathlib, sys, threading
args = sys.argv[1:]
profile = next(a.split("=", 1)[1] for a in args if a.startswith("--user-data-dir="))
pathlib.Path(profile, "fake.pid").write_text(str(os.getpid()))
pathlib.Path(profile, "env.json").write_text(json.dumps(dict(os.environ)))
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


def write_script(bin_dir: pl.Path, name: str, body: str) -> pl.Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    path = bin_dir / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def write_fakes(bin_dir: pl.Path) -> dict[str, str]:
    entries = (("chromium", FAKE_CHROMIUM, "VESTA_BROWSER_CHROMIUM"), ("browser-use", FAKE_BROWSER_USE, "VESTA_BROWSER_BROWSER_USE"))
    return {key: str(write_script(bin_dir, name, body)) for name, body, key in entries}


# The display stack's four binaries. Each fake bakes the X socket dir in at write time, because the
# real launches hand every child a closed env (PATH, HOME, DISPLAY, MOZ_ENABLE_WAYLAND) that no
# test variable can ride into. X11_DIR is that hole.
X11_DIR = "@@X11_DIR@@"

# Both socket fakes accept and drop what connects, exactly as the servers they stand in for do: a
# listener that never accepts fills its backlog and then hangs the probes a live handover runs.
ACCEPT_LOOP = """
import threading
def _accept(listener):
    while True:
        conn, _ = listener.accept()
        conn.close()
"""

FAKE_XVFB = f"""#!{sys.executable}
import os, pathlib, socket, sys, time{ACCEPT_LOOP}
number = next(a[1:] for a in sys.argv[1:] if a.startswith(":")).split(".")[0]
x11 = pathlib.Path("{X11_DIR}")
x11.mkdir(parents=True, exist_ok=True)
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.bind(str(x11 / ("X" + number)))
sock.listen(8)
(x11 / ("xvfb-" + number + ".pid")).write_text(str(os.getpid()))
open(str(x11 / "pids"), "a").write(str(os.getpid()) + "\\n")
threading.Thread(target=_accept, args=(sock,), daemon=True).start()
time.sleep(3600)
"""

FAKE_OPENBOX = f"""#!{sys.executable}
import os, time
open("{X11_DIR}/pids", "a").write(str(os.getpid()) + "\\n")
time.sleep(3600)
"""

FAKE_X11VNC = f"""#!{sys.executable}
import os, pathlib, socket, sys, time{ACCEPT_LOOP}
port = int(sys.argv[sys.argv.index("-rfbport") + 1])
open("{X11_DIR}/pids", "a").write(str(os.getpid()) + "\\n")
if pathlib.Path("{X11_DIR}", "slow").exists():
    time.sleep(3)
if pathlib.Path("{X11_DIR}", "hang").exists():
    time.sleep(3600)
if pathlib.Path("{X11_DIR}", "fail-always").exists():
    sys.exit(1)
if pathlib.Path("{X11_DIR}", "fail-shm").exists() and "-noshm" not in sys.argv:
    sys.exit(1)
sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", port))
sock.listen(8)
threading.Thread(target=_accept, args=(sock,), daemon=True).start()
time.sleep(3600)
"""

FAKE_WEBSOCKIFY = f"""#!{sys.executable}
import functools, http.server, os, sys
open("{X11_DIR}/pids", "a").write(str(os.getpid()) + "\\n")
web = sys.argv[sys.argv.index("--web") + 1]
port = int(sys.argv[-2].rsplit(":", 1)[1])
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=web)
http.server.HTTPServer(("127.0.0.1", port), handler).serve_forever()
"""


def write_display_fakes(bin_dir: pl.Path, x11_dir: pl.Path) -> None:
    x11_dir.mkdir(parents=True, exist_ok=True)
    entries = (("Xvfb", FAKE_XVFB), ("openbox", FAKE_OPENBOX), ("x11vnc", FAKE_X11VNC), ("websockify", FAKE_WEBSOCKIFY))
    for name, body in entries:
        write_script(bin_dir, name, body.replace(X11_DIR, str(x11_dir)))


# The three vestad helpers, recording what they were asked to the files FAKE_KEYS and
# FAKE_REGISTER_LOG name, so a test reads the gateway calls a run made.
FAKE_SERVICE_KEY = f"""#!{sys.executable}
import json, os, sys
cmd = sys.argv[1]
service = sys.argv[2]
state = os.environ["FAKE_KEYS"]
keys = json.load(open(state)) if os.path.exists(state) else []
if cmd == "mint":
    label = sys.argv[sys.argv.index("--label") + 1]
    ttl = sys.argv[sys.argv.index("--ttl") + 1]
    keys.append({{"id": f"id{{len(keys) + 1}}", "label": label, "ttl": int(ttl)}})
    json.dump(keys, open(state, "w"))
    print(f"secret-{{label}}")
elif cmd == "list":
    print(json.dumps({{"keys": [{{"id": k["id"], "label": k["label"]}} for k in keys]}}))
elif cmd == "revoke":
    keys = [k for k in keys if k["id"] != sys.argv[3]]
    json.dump(keys, open(state, "w"))
else:
    print("usage", file=sys.stderr); sys.exit(2)
"""

FAKE_REGISTER = f"""#!{sys.executable}
import os, sys
open(os.environ["FAKE_REGISTER_LOG"], "a").write(" ".join(sys.argv[1:]) + "\\n")
print(os.environ["FAKE_PORT"])
"""

FAKE_DEREGISTER = f"""#!{sys.executable}
import os, sys
open(os.environ["FAKE_REGISTER_LOG"], "a").write("deregister " + sys.argv[1] + "\\n")
"""


def write_gateway_fakes(bin_dir: pl.Path) -> None:
    write_script(bin_dir, "service-key", FAKE_SERVICE_KEY)
    write_script(bin_dir, "register-service", FAKE_REGISTER)
    write_script(bin_dir, "deregister-service", FAKE_DEREGISTER)
