"""App Chat CLI entry point.

Commands:
  serve   — daemon: holds a WS connection to the agent, accepts CLI commands via Unix socket to send replies
  send    — send a message to the app (via daemon Unix socket)
  history — search/list chat history via agent API
"""

import argparse
import os
import sys

from app_chat_cli.commands import cmd_send, cmd_history
from app_chat_cli.daemon import cmd_serve


def _require_ws_port() -> str:
    port = os.environ.get("WS_PORT")
    if not port:
        print("error: WS_PORT environment variable is not set", file=sys.stderr)
        sys.exit(1)
    return port


def main() -> None:
    parser = argparse.ArgumentParser(prog="app-chat", description="Vesta app chat skill")
    sub = parser.add_subparsers(dest="command")

    port = _require_ws_port()
    ws_default = f"ws://localhost:{port}/ws"
    http_default = f"http://localhost:{port}"

    serve_p = sub.add_parser("serve", help="Run the app-chat daemon")
    # LEGACY(remove-when: no running agent's restart-skill `## Daemons` line still passes
    # --notifications-dir): accepted and ignored. Intake moved to core/api.py (#809); kept so
    # existing launch lines don't break argparse.
    serve_p.add_argument("--notifications-dir", default=None, help=argparse.SUPPRESS)
    serve_p.add_argument("--ws-url", default=ws_default, help=f"Agent WebSocket URL (default: {ws_default})")
    serve_p.add_argument("--data-dir", default=None, help="Data directory (default: ~/.app-chat)")

    send_p = sub.add_parser("send", help="Send a message to the app")
    send_p.add_argument("--message", "-m", required=True, help="Message text")
    send_p.add_argument("--socket", default=None, help="Unix socket path (default: ~/.app-chat/app-chat.sock)")
    send_p.add_argument(
        "--longform",
        action="store_true",
        help="Bypass the bubble lint for genuine reference material (a brief, code block, or list they asked for)",
    )

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
