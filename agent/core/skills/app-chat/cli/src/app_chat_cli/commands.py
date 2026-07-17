"""CLI commands: send and history."""

import argparse
import asyncio
import json
import os
import pathlib as pl
import sys
import typing as tp
import urllib.error
import urllib.parse
import urllib.request

from app_chat_cli.bubblelint import bubble_lint_reason


def _default_agent_url() -> str:
    port = os.environ.get("WS_PORT")
    if not port:
        print("error: WS_PORT environment variable is not set", file=sys.stderr)
        sys.exit(1)
    return f"http://localhost:{port}"


def cmd_send(args: argparse.Namespace) -> None:
    message = args.message

    if not getattr(args, "longform", False):
        reason = bubble_lint_reason(message)
        if reason:
            print(json.dumps({"error": reason}))
            sys.exit(1)

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
        await writer.wait_closed()
        return json.loads(data.decode())
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}


def _api_get(base_url: str, path: str, params: dict[str, str]) -> dict[str, object]:
    agent_token = os.environ.get("AGENT_TOKEN")
    if agent_token:
        params = {**params, "agent_token": agent_token}
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


_MESSAGE_TYPES = ("user", "assistant", "chat")


def _recent_messages(base_url: str, limit: int) -> list[dict[str, str]] | dict[str, object]:
    """Fetch the last `limit` chat messages, paging back through /history past non-message events."""
    collected: list[dict[str, str]] = []
    cursor: int | None = None
    while len(collected) < limit:
        params = {"limit": str(limit), "cursor": str(cursor)} if cursor is not None else {"limit": str(limit)}
        data = _api_get(base_url, "/history", params)
        if "error" in data:
            return data
        if "events" not in data:
            return {"error": "unexpected response from /history"}
        events = tp.cast(list[dict[str, str]], data["events"])
        messages = [{"timestamp": e["ts"], "role": e["type"], "content": e["text"]} for e in events if e["type"] in _MESSAGE_TYPES]
        collected = messages + collected
        cursor = tp.cast("int | None", data["cursor"])
        if cursor is None:
            break
    return collected[-limit:]


def cmd_history(args: argparse.Namespace) -> None:
    query = args.search
    limit = args.limit
    base_url = args.url or _default_agent_url()

    if query:
        # Search is /history with ?q= (relevance-ranked matching events); project to the same
        # {timestamp, role, content} shape the recent path returns.
        params: dict[str, str] = {"q": query, "limit": str(limit)}
        data = _api_get(base_url, "/history", params)
        if "error" in data:
            print(json.dumps(data))
            sys.exit(1)
        if "events" not in data:
            print(json.dumps({"error": "unexpected response from /history"}))
            sys.exit(1)
        events = tp.cast(list[dict[str, str]], data["events"])
        results = [{"timestamp": e["ts"], "role": e["type"], "content": e["text"]} for e in events]
        print(json.dumps(results, indent=2))
    else:
        result = _recent_messages(base_url, limit)
        if isinstance(result, dict):
            print(json.dumps(result))
            sys.exit(1)
        print(json.dumps(result, indent=2))
