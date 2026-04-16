"""App Chat CLI entry point.

Commands:
  serve   — daemon: connects to agent WS, writes notifications, accepts CLI commands via Unix socket
  send    — send a message to the app (via daemon Unix socket)
  history — search/list chat history via agent API
"""

import argparse
import os
import sys

from app_chat_cli.commands import cmd_send, cmd_history
from app_chat_cli.daemon import cmd_serve


def _default_ws_url() -> str:
    port = os.environ.get("WS_PORT")
    if not port:
        print("error: WS_PORT environment variable is not set", file=sys.stderr)
        sys.exit(1)
    return f"ws://localhost:{port}/ws"


def _default_http_url() -> str:
    port = os.environ.get("WS_PORT")
    if not port:
        print("error: WS_PORT environment variable is not set", file=sys.stderr)
        sys.exit(1)
    return f"http://localhost:{port}"


def main() -> None:
    parser = argparse.ArgumentParser(prog="app-chat", description="Vesta app chat skill")
    sub = parser.add_subparsers(dest="command")

    ws_default = _default_ws_url()
    http_default = _default_http_url()

    serve_p = sub.add_parser("serve", help="Run the app-chat daemon")
    serve_p.add_argument("--notifications-dir", required=True, help="Directory for notification JSON files")
    serve_p.add_argument("--ws-url", default=ws_default, help=f"Agent WebSocket URL (default: {ws_default})")
    serve_p.add_argument("--data-dir", default=None, help="Data directory (default: ~/.app-chat)")

    send_p = sub.add_parser("send", help="Send a message to the app")
    send_p.add_argument("--message", "-m", required=True, help="Message text")
    send_p.add_argument("--socket", default=None, help="Unix socket path (default: ~/.app-chat/app-chat.sock)")

    history_p = sub.add_parser("history", help="Search or list chat history")
    history_p.add_argument("--search", "-s", default=None, help="FTS5 search query")
    history_p.add_argument("--limit", "-n", type=int, default=20, help="Max results")
    history_p.add_argument("--url", default=None, help=f"Agent HTTP base URL (default: {http_default})")

    args = parser.parse_args()

    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "send":
        cmd_send(args)
    elif args.command == "history":
        cmd_history(args)
    else:
        parser.print_help()
        sys.exit(1)
