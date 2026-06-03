"""Hook forwarder: invoked by `claude` as a command hook, relays stdin to the bridge.

Stdlib only — `claude` runs this as a fresh subprocess per hook event, by absolute
path, so it must not depend on the agent venv. Usage:

    python3 -m cc_sdk._forward <EventName> <unix-socket-path>

Always exits 0: a hook failure must never wedge the model's turn.
"""

import json
import socket
import sys
import typing as tp


def _request(sock_path: str, payload: dict[str, object]) -> dict[str, object]:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(15)
    client.connect(sock_path)
    try:
        client.sendall((json.dumps(payload) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = client.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        client.close()
    if not buf.strip():
        return {}
    decoded = json.loads(buf.split(b"\n", 1)[0].decode())
    return decoded if isinstance(decoded, dict) else {}


def main() -> None:
    if len(sys.argv) < 3:
        sys.stdout.write("{}")
        return
    event = sys.argv[1]
    sock_path = sys.argv[2]
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    output: dict[str, object] = {}
    try:
        reply = _request(sock_path, {"kind": "hook", "event": event, "payload": payload})
        if "output" in reply and isinstance(reply["output"], dict):
            output = tp.cast("dict[str, object]", reply["output"])
    except (OSError, ValueError):
        output = {}
    sys.stdout.write(json.dumps(output))


if __name__ == "__main__":
    main()
