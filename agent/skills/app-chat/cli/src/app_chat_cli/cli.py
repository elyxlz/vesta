"""App Chat CLI entry point.

Commands:
  serve   — daemon: runs the app-chat HTTP service (intake, history, live chat socket), accepts CLI commands via Unix socket
  daemon  — daemon lifecycle: start|stop|restart|status (idempotent start, status reports whether it is up and on which port)
  send    — send a message to the app (via daemon Unix socket)
  history — search/list chat history from the skill's own store
  import  — one-time copy of pre-existing app-chat history from core's events.db into the skill store
"""

import argparse
import sys

from app_chat_cli.commands import cmd_attachments_list, cmd_attachments_rm, cmd_history, cmd_import, cmd_send
from app_chat_cli.daemon import cmd_serve, daemon_cmd

_HELP_ARGS = ("--help", "-h", "help")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app-chat", description="Vesta app chat skill")
    sub = parser.add_subparsers(dest="command")

    serve_p = sub.add_parser("serve", help="Run the app-chat daemon in the foreground")
    # LEGACY(remove-when: no running agent's restart-skill `## Daemons` line still passes
    # --notifications-dir): accepted and ignored. Intake is owned by the HTTP service; kept so
    # existing launch lines don't break argparse.
    serve_p.add_argument("--notifications-dir", default=None, help=argparse.SUPPRESS)
    # LEGACY(remove-when: no running agent's restart-skill `## Daemons` line still passes --ws-url):
    # accepted and ignored. The daemon does not connect to core's /ws; the live echo fans out
    # in-process to the service's /ws subscribers. Kept so an existing launch line doesn't break argparse.
    serve_p.add_argument("--ws-url", default=None, help=argparse.SUPPRESS)
    serve_p.add_argument("--data-dir", default=None, help="Data directory (default: ~/.app-chat)")
    serve_p.add_argument("--port", type=int, default=None, help="Service port (default: resolved via register-service)")

    daemon_p = sub.add_parser("daemon", help="Manage the background daemon: start|stop|restart|status")
    daemon_p.add_argument("action", nargs="?", default="", metavar="start|stop|restart|status")

    send_p = sub.add_parser("send", help="Send a message to the app")
    send_p.add_argument(
        "--message",
        "-m",
        action="append",
        default=None,
        help=(
            "One bubble; repeat -m for a multi-bubble reply, sent in order. '-' (as the only -m) reads the reply from stdin, "
            "one bubble per blank-line-separated paragraph (one bubble in all under --longform)"
        ),
    )
    send_p.add_argument(
        "--gap",
        type=float,
        default=None,
        help="Seconds between bubbles of a multi-bubble reply (default ~2.5s); pass 0 for no beat",
    )
    send_p.add_argument(
        "--attach",
        action="append",
        default=[],
        metavar="PATH",
        help="Attach a file (repeatable); the daemon copies it into its own store, so a temp file may be deleted after",
    )
    send_p.add_argument("--socket", default=None, help="Unix socket path (default: ~/.app-chat/app-chat.sock)")
    send_p.add_argument(
        "--longform",
        action="store_true",
        help="Bypass the bubble lint for genuine reference material (a brief, code block, or list they asked for)",
    )

    attachments_p = sub.add_parser("attachments", help="Inspect and clean up attachment disk usage")
    att_sub = attachments_p.add_subparsers(dest="action")
    att_list_p = att_sub.add_parser("list", help="List attachments with sizes and totals (largest first)")
    att_list_p.add_argument("--sort", choices=("size", "date"), default="size", help="Order: size (largest first) or date (newest first)")
    att_list_p.add_argument("--limit", type=int, default=None, help="Trim the printed array (count/total_bytes still cover everything)")
    att_list_p.add_argument("--min-size", dest="min_size", type=int, default=None, metavar="BYTES", help="Only attachments at least this big")
    att_list_p.add_argument("--data-dir", default=None, help="Data directory (default: ~/.app-chat)")
    att_rm_p = att_sub.add_parser("rm", help="Free an attachment's bytes; chat history keeps a clean 'no longer available' tile")
    att_rm_p.add_argument("ids", nargs="+", metavar="ID")
    att_rm_p.add_argument("--data-dir", default=None, help="Data directory (default: ~/.app-chat)")

    history_p = sub.add_parser("history", help="Search or list chat history")
    history_p.add_argument("--search", "-s", default=None, help="FTS5 search query")
    history_p.add_argument("--limit", "-n", type=int, default=20, help="Max results")
    history_p.add_argument("--data-dir", default=None, help="Data directory (default: ~/.app-chat)")

    import_p = sub.add_parser("import", help="Copy pre-existing app-chat history from core's events.db into the skill store")
    import_p.add_argument("--events-db", default=None, help="Path to core's events.db (default: $AGENT_DIR/data/events.db)")
    import_p.add_argument("--data-dir", default=None, help="Data directory (default: ~/.app-chat)")

    return parser


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in _HELP_ARGS:
        _build_parser().print_help()
        sys.exit(0)

    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "daemon":
        sys.exit(daemon_cmd(args.action))
    elif args.command == "send":
        cmd_send(args)
    elif args.command == "attachments":
        if args.action == "list":
            cmd_attachments_list(args)
        elif args.action == "rm":
            cmd_attachments_rm(args)
        else:
            parser.print_help()
            sys.exit(1)
    elif args.command == "history":
        cmd_history(args)
    elif args.command == "import":
        cmd_import(args)
    else:
        parser.print_help()
        sys.exit(1)
