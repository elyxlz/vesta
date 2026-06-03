"""MCP stdio proxy: the server `claude` spawns for the in-process `vesta` tools.

Stdlib only. Speaks newline-delimited JSON-RPC on stdin/stdout. tools/call is
forwarded to the bridge unix socket, where the real handlers run inside the agent
process. tools/list is served from a static defs file (when given) so startup tool
registration never depends on the live bridge. Usage:

    python3 -m cc_sdk._mcp_stdio <unix-socket-path> [<tools-json-path>]
"""

import json
import socket
import sys
import time
import typing as tp

_DEFAULT_PROTOCOL = "2025-06-18"
# Retry the bridge connect briefly: claude can spawn this proxy and fire its startup
# tools/list before the agent's bridge socket is accepting, especially under first-start
# load. A failed connect here makes claude mark the whole MCP server dead for the session,
# so a few retries are the difference between working tools and silently-missing tools.
_CONNECT_RETRIES = 40
_CONNECT_BACKOFF_S = 0.25


def _connect(sock_path: str) -> socket.socket:
    last_err: OSError | None = None
    for _ in range(_CONNECT_RETRIES):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(60)
        try:
            client.connect(sock_path)
            return client
        except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
            last_err = exc
            client.close()
            time.sleep(_CONNECT_BACKOFF_S)
    raise last_err if last_err is not None else OSError(f"could not connect to {sock_path}")


def _bridge(sock_path: str, payload: dict[str, tp.Any]) -> dict[str, tp.Any]:
    client = _connect(sock_path)
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


def _send(message: dict[str, tp.Any]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def _static_tools(tools_path: str | None) -> list[dict[str, tp.Any]] | None:
    """Tool definitions claude lists at startup, served from a file cc_sdk wrote — NOT the
    live bridge. The bridge runs in the agent's event loop and, at first-start, claude's
    startup tools/list against it does not reliably register the tools (observed: the model
    then can't call mark_setup_done at all). The defs are static and known at config time, so
    serving them locally makes registration deterministic; only tools/call needs the bridge."""
    if not tools_path:
        return None
    try:
        with open(tools_path) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) else None


def _handle(sock_path: str, request: dict[str, tp.Any], tools_path: str | None) -> dict[str, tp.Any] | None:
    method = request["method"] if "method" in request else ""
    has_id = "id" in request
    request_id = request["id"] if has_id else None
    params = request["params"] if "params" in request and isinstance(request["params"], dict) else {}

    if method == "initialize":
        protocol = params["protocolVersion"] if "protocolVersion" in params else _DEFAULT_PROTOCOL
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "vesta", "version": "1.0.0"},
            },
        }
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        tools = _static_tools(tools_path)
        if tools is None:
            reply = _bridge(sock_path, {"kind": "mcp", "op": "list"})
            tools = reply["tools"] if "tools" in reply else []
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}
    if method == "tools/call":
        name = params["name"] if "name" in params else ""
        arguments = params["arguments"] if "arguments" in params and isinstance(params["arguments"], dict) else {}
        reply = _bridge(sock_path, {"kind": "mcp", "op": "call", "name": name, "arguments": arguments})
        if "content" in reply:
            return {"jsonrpc": "2.0", "id": request_id, "result": {"content": reply["content"], "isError": False}}
        error = reply["error"] if "error" in reply else "tool call failed"
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"content": [{"type": "text", "text": str(error)}], "isError": True},
        }
    if has_id:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return None


def main() -> None:
    if len(sys.argv) < 2:
        return
    sock_path = sys.argv[1]
    tools_path = sys.argv[2] if len(sys.argv) > 2 else None
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(request, dict):
            continue
        try:
            response = _handle(sock_path, request, tools_path)
        except (OSError, ValueError) as exc:
            response = None
            if "id" in request:
                response = {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32603, "message": str(exc)}}
        if response is not None:
            _send(response)


if __name__ == "__main__":
    main()
