import argparse
import json
import logging
import os
import signal
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

from . import commands, daemon, db
from . import format as fmt
from .config import Config
from .nudge import tick, write_notification
from .settings import SETTING_NAMES, Settings, load_settings, set_setting

DEFAULT_TICK_SECS = 60

USAGE = (
    """usage: flashcards add --deck <deck> "<front>" "<back>" [--notes <text>]
       flashcards add --deck <deck> --file <cards.json>       # a JSON list of {"front", "back", "notes"?}; "-" reads stdin
       flashcards next [--deck <deck>]                        # the one card to ask now, with how many remain
       flashcards review <id> again|hard|good|easy [--seconds N]
       flashcards due [--deck <deck>] [--limit N] [--json]
       flashcards list [--deck <deck>] [--json]
       flashcards get <id>
       flashcards update <id> [--front ..] [--back ..] [--notes ..] [--deck ..]
       flashcards delete <id> | suspend <id> | resume <id>
       flashcards deck list [--json] | deck update <name> [--name ..] [--description ..] | deck delete <name>
       flashcards stats
       flashcards config [<name> <value>]                     # names: """
    + ", ".join(SETTING_NAMES)
    + """
       flashcards daemon start|stop|restart|status

Ratings: again = forgot; hard = recalled with real difficulty; good = recalled after a pause; easy = instant.
Every command prints one line of JSON on stdout (tables for list, due, deck list unless --json);
a failure prints {"error": ...} on stderr and exits 1."""
)


def _fail(message: str) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return 1


def _emit(data: object, *, pretty: bool = False) -> None:
    if pretty:
        print(json.dumps(data, indent=2))
    else:
        print(json.dumps(data))


def _add_format_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true", help="one-line JSON instead of a table")
    group.add_argument("--json-pretty", action="store_true", help="indented JSON instead of a table")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flashcards", usage=USAGE, add_help=False)
    sub = parser.add_subparsers(dest="command", required=True, prog="flashcards")

    add = sub.add_parser("add")
    add.add_argument("--deck", required=True)
    add.add_argument("front", nargs="?")
    add.add_argument("back", nargs="?")
    add.add_argument("--notes", default="")
    add.add_argument("--file", help='JSON list of {"front", "back", "notes"?}; "-" for stdin')

    for name in ("next", "due", "list"):
        p = sub.add_parser(name)
        p.add_argument("--deck")
        if name == "due":
            p.add_argument("--limit", type=int)
        if name != "next":
            _add_format_flags(p)

    rev = sub.add_parser("review")
    rev.add_argument("id", type=int)
    rev.add_argument("rating", choices=list(commands.RATINGS))
    rev.add_argument("--seconds", type=int, help="how long the answer took, when known")

    for name in ("get", "delete", "suspend", "resume"):
        sub.add_parser(name).add_argument("id", type=int)

    upd = sub.add_parser("update")
    upd.add_argument("id", type=int)
    for flag in ("--front", "--back", "--notes", "--deck"):
        upd.add_argument(flag)

    deck = sub.add_parser("deck").add_subparsers(dest="deck_command", required=True)
    _add_format_flags(deck.add_parser("list"))
    deck_update = deck.add_parser("update")
    deck_update.add_argument("name")
    deck_update.add_argument("--name", dest="new_name")
    deck_update.add_argument("--description")
    deck.add_parser("delete").add_argument("name")

    sub.add_parser("stats")
    config = sub.add_parser("config")
    config.add_argument("name", nargs="?")
    config.add_argument("value", nargs="?")

    sub.add_parser("daemon").add_argument("action", nargs="?", default="")
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, help="HTTP port allocated by vestad; omitted when the API is off")
    serve.add_argument("--notifications-dir", default=str(Path.home() / "agent" / "notifications"))
    return parser


def _read_cards_file(path: str) -> list[tuple[str, str, str]]:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text()
    items = json.loads(raw)
    if not isinstance(items, list):
        raise ValueError("the cards file must hold a JSON list of objects with front and back")
    cards = []
    for item in items:
        if not isinstance(item, dict) or "front" not in item or "back" not in item:
            raise ValueError("every entry needs a front and a back")
        cards.append((str(item["front"]), str(item["back"]), str(item["notes"]) if "notes" in item else ""))
    return cards


def _add_items(args: argparse.Namespace) -> list[tuple[str, str, str]]:
    if args.file:
        return _read_cards_file(args.file)
    if args.front and args.back:
        return [(args.front, args.back, args.notes)]
    raise ValueError('add needs a front and a back, or --file: flashcards add --deck <deck> "<front>" "<back>"')


def _run(args: argparse.Namespace, config: Config) -> int:
    now = db.utc_now()
    with closing(db.get_db(config.data_dir)) as conn:
        settings = load_settings(conn)
        if args.command == "add":
            _emit(commands.cards_add(conn, args.deck, _add_items(args), now=now))
        elif args.command == "next":
            _emit(commands.next_card(conn, settings, now=now, deck=args.deck))
        elif args.command == "due":
            _emit_cards(commands.due_cards(conn, settings, now=now, deck=args.deck, limit=args.limit), args, now)
        elif args.command == "list":
            _emit_cards(commands.card_list(conn, deck=args.deck), args, now)
        elif args.command == "deck":
            _run_deck(args, conn, now)
        elif args.command == "stats":
            _emit(commands.stats(conn, settings, now=now))
        elif args.command == "config":
            _run_config(args, conn, settings)
        else:
            _run_card(args, conn, settings, now)
    return 0


def _run_card(args: argparse.Namespace, conn: sqlite3.Connection, settings: Settings, now: datetime) -> None:
    if args.command == "review":
        _emit(commands.review(conn, settings, args.id, args.rating, now=now, seconds=args.seconds))
    elif args.command == "get":
        _emit(commands.card_get(conn, args.id))
    elif args.command == "update":
        _emit(commands.card_update(conn, args.id, front=args.front, back=args.back, notes=args.notes, deck=args.deck, now=now))
    elif args.command == "delete":
        _emit(commands.card_delete(conn, args.id, now=now))
    else:
        _emit(commands.card_suspend(conn, args.id, suspended=args.command == "suspend", now=now))


def _run_config(args: argparse.Namespace, conn: sqlite3.Connection, settings: Settings) -> None:
    if args.name is None:
        _emit(settings.__dict__)
    elif args.value is None:
        raise ValueError(f"config {args.name} needs a value: flashcards config {args.name} <value>")
    else:
        _emit(set_setting(conn, args.name, args.value).__dict__)


def _emit_cards(cards: list[commands.Card], args: argparse.Namespace, now: datetime) -> None:
    if args.json or args.json_pretty:
        _emit(cards, pretty=args.json_pretty)
    else:
        print(fmt.format_cards([dict(card) for card in cards], now))


def _run_deck(args: argparse.Namespace, conn: sqlite3.Connection, now: datetime) -> None:
    if args.deck_command == "list":
        decks = commands.deck_list(conn, now=now)
        if args.json or args.json_pretty:
            _emit(decks, pretty=args.json_pretty)
        else:
            print(fmt.format_decks([dict(deck) for deck in decks]))
    elif args.deck_command == "update":
        _emit(commands.deck_update(conn, args.name, new_name=args.new_name, description=args.description, now=now))
    elif args.deck_command == "delete":
        _emit(commands.deck_delete(conn, args.name, now=now))


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(USAGE)
        return
    if argv[0] == "daemon" and len(argv) > 1 and argv[1] in ("help", "-h", "--help"):
        print(daemon.USAGE)
        return
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse has already printed its message on stderr; the exit code is the contract's.
        sys.exit(1 if exc.code else 0)

    config = Config()
    config.log_dir.mkdir(parents=True, exist_ok=True)
    db.init_db(config.data_dir)

    if args.command == "daemon":
        sys.exit(daemon.daemon_cmd(args.action))
    if args.command == "serve":
        _run_serve(config, Path(args.notifications_dir), port=args.port)
        return
    try:
        sys.exit(_run(args, config))
    except (ValueError, OSError) as exc:
        sys.exit(_fail(str(exc)))


def _run_serve(config: Config, notif_dir: Path, *, port: int | None) -> None:
    notif_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(config.log_dir / "daemon.log"), logging.StreamHandler()],
    )
    from .server import start_server

    shutdown_reason = "unknown"
    asked_to_stop = False

    def handle_signal(signum, _frame):
        # SIGTERM is what `flashcards daemon stop` sends, the one exit the agent asked for; every
        # other way out is news the agent needs.
        nonlocal shutdown_reason, asked_to_stop
        shutdown_reason = signal.Signals(signum).name
        asked_to_stop = signum == signal.SIGTERM
        raise SystemExit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    http_server = start_server(config, port) if port is not None else None
    tick_secs = int(os.environ["FLASHCARDS_TICK_SECS"]) if "FLASHCARDS_TICK_SECS" in os.environ else DEFAULT_TICK_SECS
    print(json.dumps({"status": "serving", "tick_secs": tick_secs, "http_port": port}))
    sys.stdout.flush()
    try:
        while True:
            time.sleep(tick_secs)
            try:
                with closing(db.get_db(config.data_dir)) as conn:
                    if tick(conn, notif_dir, now=db.utc_now()):
                        logging.getLogger(__name__).info("wrote cards_due notification")
            except Exception:
                # A bad tick (locked db, malformed row) must not kill the daemon; retry next tick.
                logging.getLogger(__name__).exception("tick failed")
    finally:
        if http_server is not None:
            http_server.should_exit = True
        if not asked_to_stop:
            write_notification(notif_dir, "daemon_died", reason=shutdown_reason)
