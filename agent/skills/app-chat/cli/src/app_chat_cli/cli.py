"""App Chat CLI entry point.

Commands:
  serve   — daemon: connects to agent WS, writes notifications, accepts CLI commands via Unix socket
  send    — send a message to the app (via daemon Unix socket)
  history — search/list chat history via agent API
"""

import argparse
import sys

from app_chat_cli.commands import cmd_send, cmd_history
from app_chat_cli.daemon import cmd_serve


def main() -> None:
    parser = argparse.ArgumentParser(prog="app-chat", description="Vesta app chat skill")
    sub = parser.add_subparsers(dest="command")

    serve_p = sub.add_parser("serve", help="Run the app-chat daemon")
    serve_p.add_argument("--notifications-dir", required=True, help="Directory for notification JSON files")
    serve_p.add_argument("--ws-url", default="ws://localhost:7865/ws", help="Agent WebSocket URL")
    serve_p.add_argument("--data-dir", default=None, help="Data directory (default: ~/.app-chat)")

    send_p = sub.add_parser("send", help="Send a message to the app")
    send_p.add_argument("--message", "-m", required=True, help="Message text")
    send_p.add_argument("--socket", default=None, help="Unix socket path (default: ~/.app-chat/app-chat.sock)")

    history_p = sub.add_parser("history", help="Search or list chat history")
    history_p.add_argument("--search", "-s", default=None, help="FTS5 search query")
    history_p.add_argument("--limit", "-n", type=int, default=20, help="Max results")
    history_p.add_argument("--url", default=None, help="Agent HTTP base URL (default: http://localhost:7865)")

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
