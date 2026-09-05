"""Chat CLI entry point.

Commands:
  serve   — daemon: runs the chat HTTP service (intake, history, live chat socket), accepts CLI commands via Unix socket
  daemon  — daemon lifecycle: start|stop|restart|status (idempotent start, status reports whether it is up and on which port)
  send    — send a message into a room (via daemon Unix socket)
  rooms   — list the rooms this agent is in, or open a new one
  peers   — list the other agents on this gateway
  history — search/list chat history from the skill's own store
  import  — one-time copy of pre-existing chat history from core's events.db into the skill store
  import-to-node — hand the node the direct conversation this store already holds
"""

import argparse
import sys
import typing as tp

from chat_cli.commands import (
    cmd_attachments_list,
    cmd_attachments_rm,
    cmd_history,
    cmd_import,
    cmd_import_to_node,
    cmd_peers,
    cmd_rooms,
    cmd_rooms_create,
    cmd_send,
)
from chat_cli.daemon import cmd_serve, daemon_cmd

_HELP_ARGS = ("--help", "-h", "help")

# Every verb and what runs it. A verb with sub-verbs is keyed by both names, so the dispatch below
# stays one lookup whatever shape a command has.
_VERBS: dict[str, tp.Callable[[argparse.Namespace], None]] = {
    "serve": cmd_serve,
    "send": cmd_send,
    "peers": cmd_peers,
    "history": cmd_history,
    "import": cmd_import,
    "import-to-node": cmd_import_to_node,
}
_SUB_VERBS: dict[tuple[str, str | None], tp.Callable[[argparse.Namespace], None]] = {
    ("rooms", None): cmd_rooms,
    ("rooms", "create"): cmd_rooms_create,
    ("attachments", "list"): cmd_attachments_list,
    ("attachments", "rm"): cmd_attachments_rm,
}


def _handler(args: argparse.Namespace) -> tp.Callable[[argparse.Namespace], None] | None:
    """What runs this command line, or None when the parser accepted a verb with no sub-verb to run."""
    if "action" in args:
        key = (args.command, args.action)
        return _SUB_VERBS[key] if key in _SUB_VERBS else None
    return _VERBS[args.command] if args.command in _VERBS else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chat", description="Vesta chat skill")
    sub = parser.add_subparsers(dest="command")

    serve_p = sub.add_parser("serve", help="Run the chat daemon in the foreground")
    # LEGACY(remove-when: no running agent's restart-skill `## Daemons` line still passes
    # --notifications-dir): accepted and ignored. Intake is owned by the HTTP service; kept so
    # existing launch lines don't break argparse.
    serve_p.add_argument("--notifications-dir", default=None, help=argparse.SUPPRESS)
    # LEGACY(remove-when: no running agent's restart-skill `## Daemons` line still passes --ws-url):
    # accepted and ignored. The daemon does not connect to core's /ws; the live echo fans out
    # in-process to the service's /ws subscribers. Kept so an existing launch line doesn't break argparse.
    serve_p.add_argument("--ws-url", default=None, help=argparse.SUPPRESS)
    serve_p.add_argument("--data-dir", default=None, help="Data directory (default: ~/.chat)")
    serve_p.add_argument("--port", type=int, default=None, help="Service port (default: resolved via register-service)")

    daemon_p = sub.add_parser("daemon", help="Manage the background daemon: start|stop|restart|status")
    daemon_p.add_argument("action", nargs="?", default="", metavar="start|stop|restart|status")

    send_p = sub.add_parser("send", help="Send a message into a room (the conversation with the user by default)")
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
        help="Attach a file (repeatable); the daemon uploads it and keeps a copy, so a temp file may be deleted after",
    )
    send_p.add_argument("--socket", default=None, help="Unix socket path (default: ~/.chat/chat.sock)")
    target = send_p.add_mutually_exclusive_group()
    target.add_argument("--to", default=None, metavar="AGENT", help="Send to another agent, opening the room with them if it is new")
    target.add_argument("--room", default=None, metavar="ID", help="Send into a room by id (default: the conversation with the user)")
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
    att_list_p.add_argument("--data-dir", default=None, help="Data directory (default: ~/.chat)")
    att_rm_p = att_sub.add_parser("rm", help="Free an attachment's bytes; chat history keeps a clean 'no longer available' tile")
    att_rm_p.add_argument("ids", nargs="+", metavar="ID")
    att_rm_p.add_argument("--data-dir", default=None, help="Data directory (default: ~/.chat)")

    rooms_p = sub.add_parser("rooms", help="List the rooms this agent is in, or open a new one")
    rooms_p.add_argument("--json", action="store_true", help="Print the rooms as one JSON list")
    rooms_sub = rooms_p.add_subparsers(dest="action")
    rooms_create_p = rooms_sub.add_parser("create", help="Open a room with the agents named")
    rooms_create_p.add_argument("--name", required=True, help="What the room is called")
    rooms_create_p.add_argument("--agents", required=True, metavar="A,B", help="Comma-separated agent names; this agent is always in it")

    peers_p = sub.add_parser("peers", help="List the other agents on this gateway")
    peers_p.add_argument("--json", action="store_true", help="Print the names as one JSON list")

    history_p = sub.add_parser("history", help="Search or list chat history")
    history_p.add_argument("--room", default=None, metavar="ID", help="Read one room (default: the conversation with the user)")
    history_p.add_argument("--search", "-s", default=None, help="FTS5 search query")
    history_p.add_argument("--limit", "-n", type=int, default=20, help="Max results")
    history_p.add_argument("--data-dir", default=None, help="Data directory (default: ~/.chat)")

    import_p = sub.add_parser("import", help="Copy pre-existing chat history from core's events.db into the skill store")
    import_p.add_argument("--events-db", default=None, help="Path to core's events.db (default: $AGENT_DIR/data/events.db)")
    import_p.add_argument("--data-dir", default=None, help="Data directory (default: ~/.chat)")

    to_node_p = sub.add_parser("import-to-node", help="Hand the node the direct conversation this store already holds")
    to_node_p.add_argument("--data-dir", default=None, help="Data directory (default: ~/.chat)")

    return parser


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in _HELP_ARGS:
        _build_parser().print_help()
        sys.exit(0)

    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "daemon":
        # The one verb that answers with an exit code rather than printed output.
        sys.exit(daemon_cmd(args.action))
    handler = _handler(args)
    if handler is None:
        parser.print_help()
        sys.exit(1)
    handler(args)
