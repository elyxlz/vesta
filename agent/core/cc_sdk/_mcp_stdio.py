"""MCP stdio proxy: the server `claude` spawns for the in-process `vesta` tools.

Stdlib only. Speaks newline-delimited JSON-RPC on stdin/stdout and forwards
tools/list and tools/call to the bridge unix socket, where the real handlers run
inside the agent process. Usage:

    python3 -m cc_sdk._mcp_stdio <unix-socket-path>
"""

import json
import socket
import sys
import typing as tp

_DEFAULT_PROTOCOL = "2025-06-18"


def _bridge(sock_path: str, payload: dict[str, tp.Any]) -> dict[str, tp.Any]:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(60)
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


def _send(message: dict[str, tp.Any]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def _handle_tools(sock_path: str, method: str, request_id: int | str | None, params: dict[str, tp.Any]) -> dict[str, tp.Any]:
    if method == "tools/list":
        reply = _bridge(sock_path, {"kind": "mcp", "op": "list"})
        tools = reply["tools"] if "tools" in reply else []
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}
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


def _handle(sock_path: str, request: dict[str, tp.Any]) -> dict[str, tp.Any] | None:
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
    if method in ("tools/list", "tools/call"):
        return _handle_tools(sock_path, method, request_id, params)
    if has_id:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return None


def main() -> None:
    if len(sys.argv) < 2:
        return
    sock_path = sys.argv[1]
    for line in sys.stdin:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            request = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(request, dict):
            continue
        try:
            response = _handle(sock_path, request)
        except (OSError, ValueError) as exc:
            response = None
            if "id" in request:
                response = {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32603, "message": str(exc)}}
        if response is not None:
            _send(response)


if __name__ == "__main__":
    main()
