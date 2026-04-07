"""CLI commands: send and history."""

import asyncio
import json
import pathlib as pl
import sys
import urllib.request
import urllib.error
import urllib.parse

DEFAULT_AGENT_URL = "http://localhost:7860"


def cmd_send(args: object) -> None:
    message = args.message
    sock_path = pl.Path(args.socket or (pl.Path.home() / ".app-chat" / "app-chat.sock"))

    if not sock_path.exists():
        print(json.dumps({"error": f"daemon not running (no socket at {sock_path})"}))
        sys.exit(1)

    result = asyncio.run(_send_via_socket(sock_path, message))
    print(json.dumps(result))
    if "error" in result:
        sys.exit(1)


async def _send_via_socket(sock_path: pl.Path, message: str) -> dict[str, object]:
    try:
        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        request = json.dumps({"command": "send", "message": message})
        writer.write(request.encode())
        writer.write_eof()
        data = await asyncio.wait_for(reader.read(65536), timeout=10.0)
        writer.close()
        return json.loads(data.decode())
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}


def _api_get(base_url: str, path: str, params: dict[str, str]) -> dict[str, object]:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{base_url}{path}?{qs}" if qs else f"{base_url}{path}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"error": f"HTTP {exc.code}: {body}"}
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return {"error": str(exc)}


def cmd_history(args: object) -> None:
    query = args.search
    limit = args.limit
    base_url = args.url or DEFAULT_AGENT_URL

    if query:
        params: dict[str, str] = {"q": query, "limit": str(limit)}
        data = _api_get(base_url, "/search", params)
        if "error" in data:
            print(json.dumps(data))
            sys.exit(1)
        print(json.dumps(data["results"], indent=2))
    else:
        params = {"limit": str(limit)}
        data = _api_get(base_url, "/history", params)
        if "error" in data:
            print(json.dumps(data))
            sys.exit(1)
        events = data["events"]
        results = [
            {"timestamp": e.get("ts", ""), "role": e.get("type", ""), "content": e.get("text", "")}
            for e in events
            if e.get("type") in ("user", "assistant", "chat")
        ]
        print(json.dumps(results, indent=2))
