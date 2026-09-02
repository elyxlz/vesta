import argparse
import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import commands, daemon, db
from . import format as fmt
from .config import Config
from .scheduler import write_notification


def _add_format_flags(parser: argparse.ArgumentParser) -> None:
    """Attach mutually-exclusive --json / --json-pretty flags to a list-style subparser."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true", help="Emit compact JSON instead of a table.")
    group.add_argument("--json-pretty", action="store_true", help="Emit indented JSON instead of a table.")


def _require_arg(value: str | None, name: str, usage: str) -> str:
    if not value:
        raise ValueError(f"{name} is required: {usage}")
    return value


# Soft cap only: a warning, never a rejection, because a legitimately long subject exists. The
# subject is the one field every list and digest shows, so detail belongs in metadata, not here.
SUBJECT_SOFT_CAP_CHARS = 100


def _warn_long_subject(subject: str) -> None:
    if len(subject) <= SUBJECT_SOFT_CAP_CHARS:
        return
    msg = (
        f"subject is {len(subject)} chars; keep the subject short and scannable, and put the detail "
        "in the task's metadata instead (the metadata_path file in this result, or --initial-metadata on create)"
    )
    print(json.dumps({"warning": msg}), file=sys.stderr)


def _require_daemon():
    if daemon.live_pid() is None:
        msg = "daemon not running, start it with: tasks daemon start"
        print(json.dumps({"error": msg}), file=sys.stderr)
        sys.exit(1)


def _add_due_args(parser: argparse.ArgumentParser) -> None:
    """The shared due-date flags: an absolute datetime, or a relative offset.

    Each flag answers to the same spelling `create`, `update`, and `postpone` use (--at, --tz,
    --in-*), so one time vocabulary works across every command; the --due-* forms are aliases."""
    parser.add_argument("--at", "--due-datetime", dest="due_datetime", default=None, help="Absolute due datetime, e.g. 2026-12-01T10:00:00")
    parser.add_argument("--tz", "--timezone", dest="timezone", default=None, help="IANA timezone; omit to use the agent's own timezone")
    parser.add_argument("--in-minutes", "--due-in-minutes", dest="due_in_minutes", type=int, default=None)
    parser.add_argument("--in-hours", "--due-in-hours", dest="due_in_hours", type=int, default=None)
    parser.add_argument("--in-days", "--due-in-days", dest="due_in_days", type=int, default=None)


def _due_spec(args: argparse.Namespace, *, clear: bool = False) -> commands.DueSpec:
    """The DueSpec the flags from `_add_due_args` describe."""
    return commands.DueSpec(
        due_datetime=args.due_datetime,
        timezone=args.timezone,
        due_in_minutes=args.due_in_minutes,
        due_in_hours=args.due_in_hours,
        due_in_days=args.due_in_days,
        clear=clear,
    )


def _add_id_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("id_pos", nargs="?", default=None, metavar="id")
    parser.add_argument("--id", default=None, dest="task_id")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tasks")
    sub = parser.add_subparsers(dest="command", required=True)

    # serve
    p_serve = sub.add_parser("serve", help="Run background daemon (task due-date monitor + digest)")
    p_serve.add_argument("--notifications-dir", default=str(Path.home() / "agent" / "notifications"))
    p_serve.add_argument("--port", type=int, required=True, help="HTTP server port (allocated by vestad)")

    # daemon
    p_daemon = sub.add_parser("daemon", help="Manage the background daemon: start|stop|restart|status")
    p_daemon.add_argument("action", nargs="?", default="", metavar="start|stop|restart|status")

    # create
    p_create = sub.add_parser("create", help="Create a new task")
    p_create.add_argument("subject_pos", nargs="?", default=None, metavar="subject")
    p_create.add_argument("--subject", default=None)
    _add_due_args(p_create)
    p_create.add_argument("--priority", default="normal", help="low/normal/high or 1/2/3")
    p_create.add_argument("--initial-metadata", default=None)

    # list
    p_list = sub.add_parser("list", help="List tasks")
    p_list.add_argument("--show-completed", action="store_true")
    p_list.add_argument("--show-deleted", action="store_true", help="Include soft-deleted tasks, marked [deleted]")
    _add_format_flags(p_list)

    # get
    p_get = sub.add_parser("get", help="Get a task by ID")
    _add_id_args(p_get)
    p_get.add_argument(
        "--field",
        action="append",
        default=None,
        choices=list(commands.TASK_FIELDS),
        help="Return only the named field(s). Repeat for multiple. Skips reading metadata unless --field metadata.",
    )

    # update
    p_update = sub.add_parser("update", help="Update a task")
    _add_id_args(p_update)
    p_update.add_argument("--status", default=None, help="pending, in_progress, or completed")
    p_update.add_argument("--subject", default=None)
    p_update.add_argument("--priority", default=None)
    _add_due_args(p_update)
    p_update.add_argument("--clear-due", action="store_true", help="Remove the task's due date, which silences its pre-due checkpoints")
    p_update.add_argument(
        "--backburner",
        dest="backburner",
        action="store_true",
        default=None,
        help="Park a deliberately undated task so the stale digest stops listing it (still pending, still in `tasks list`)",
    )
    p_update.add_argument(
        "--no-backburner", dest="backburner", action="store_false", help="Undo --backburner; the digest will list it again once stale"
    )

    # done
    p_done = sub.add_parser("done", help="Mark a task completed")
    _add_id_args(p_done)

    # postpone
    p_postpone = sub.add_parser("postpone", help="Set a new due date measured from now (also gives undated tasks one)")
    _add_id_args(p_postpone)
    _add_due_args(p_postpone)

    # delete
    p_delete = sub.add_parser("delete", help="Delete a task")
    _add_id_args(p_delete)

    # search
    p_search = sub.add_parser("search", help="Search tasks by subject")
    p_search.add_argument("query_pos", nargs="?", default=None, metavar="query")
    p_search.add_argument("--query", default=None)
    p_search.add_argument("--show-completed", action="store_true")
    p_search.add_argument("--show-deleted", action="store_true", help="Include soft-deleted tasks, marked [deleted]")
    _add_format_flags(p_search)

    return parser


def main():
    parser = _build_parser()
    if len(sys.argv) == 1 or sys.argv[1] == "help":
        parser.print_help()
        return

    args = parser.parse_args()
    config = Config()

    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)

    db.init_db(config.data_dir)

    try:
        if args.command == "serve":
            _run_serve(config, Path(args.notifications_dir), port=args.port)
            return

        if args.command == "daemon":
            sys.exit(daemon.daemon_cmd(args.action))

        _require_daemon()
        _handle_task(args, config)

    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


def _agent_name() -> str:
    return os.environ["AGENT_NAME"] if "AGENT_NAME" in os.environ else "Vesta"


def _notify_user_task(title: str) -> None:
    """Surface task activity to the app clients: kind `task` on the vestad user-notification
    helper, title-only (the title is the whole one-line message). Fire-and-forget, so a missing
    helper or unreachable gateway never fails the command (the task write already happened)."""
    with contextlib.suppress(OSError):
        subprocess.Popen(
            ["user-notification", "task", title],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _handle_task(args, config: Config):
    if args.command == "create":
        subject = _require_arg(args.subject_pos or args.subject, "subject", 'tasks create "subject" or tasks create --subject "subject"')
        _warn_long_subject(subject)
        result = commands.add_task(
            config,
            subject=subject,
            due=_due_spec(args),
            priority=args.priority,
            initial_metadata=args.initial_metadata,
        )
        _notify_user_task(f"{_agent_name()} added a task: {subject}")
        print(json.dumps(result))
        return
    if args.command == "list":
        _print_list(args, commands.list_tasks(config, show_completed=args.show_completed, show_deleted=args.show_deleted), fmt.format_task_list)
        return
    if args.command == "get":
        task_id = _require_arg(args.id_pos or args.task_id, "id", "tasks get <id> or tasks get --id <id>")
        if args.field:
            fields = list(args.field)
            result = commands.get_task_fields(config, task_id=task_id, fields=fields)
            _print_get_field_result(fields, result)
            return
        result = commands.get_task(config, task_id=task_id)
    elif args.command == "update":
        task_id = _require_arg(args.id_pos or args.task_id, "id", "tasks update <id> or tasks update --id <id>")
        subject = args.subject
        if subject is not None:
            _warn_long_subject(subject)
        result = commands.update_task(
            config,
            task_id=task_id,
            status=args.status,
            subject=subject,
            priority=args.priority,
            due=_due_spec(args, clear=args.clear_due),
            backburner=args.backburner,
        )
        if args.status == "completed":
            _notify_user_task(f"{_agent_name()} completed a task: {result['subject']}")
    elif args.command == "done":
        task_id = _require_arg(args.id_pos or args.task_id, "id", "tasks done <id> or tasks done --id <id>")
        result = commands.update_task(config, task_id=task_id, status="completed")
        _notify_user_task(f"{_agent_name()} completed a task: {result['subject']}")
    elif args.command == "postpone":
        task_id = _require_arg(args.id_pos or args.task_id, "id", "tasks postpone <id> --in-days N")
        result = commands.postpone_task(config, task_id=task_id, due=_due_spec(args))
    elif args.command == "delete":
        task_id = _require_arg(args.id_pos or args.task_id, "id", "tasks delete <id> or tasks delete --id <id>")
        result = commands.delete_task(config, task_id=task_id)
    elif args.command == "search":
        query = _require_arg(args.query_pos or args.query, "query", 'tasks search "query" or tasks search --query "query"')
        _print_list(
            args,
            commands.search_tasks(config, query=query, show_completed=args.show_completed, show_deleted=args.show_deleted),
            fmt.format_task_list,
        )
        return
    else:
        return

    print(json.dumps(result))


def _print_list(args, result: list, formatter) -> None:
    """Dispatch a list-style command result to --json-pretty / --json / compact formatter."""
    attrs = vars(args)
    if attrs.get("json_pretty"):
        print(json.dumps(result, indent=2))
    elif attrs.get("json"):
        print(json.dumps(result))
    else:
        print(formatter(result))


def _print_get_field_result(fields: list[str], result: dict) -> None:
    """Raw field values: one field prints the value alone; multiple are tab-separated."""
    values = ["" if (f not in result or result[f] is None) else str(result[f]) for f in fields]
    print(values[0] if len(values) == 1 else "\t".join(values))


def _run_serve(config: Config, notif_dir: Path, *, port: int):
    notif_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(config.log_dir / "daemon.log"),
            logging.StreamHandler(),
        ],
    )

    from .server import start_server

    shutdown_reason = "unknown"
    asked_to_stop = False

    def handle_signal(signum, _frame):
        # SIGTERM is what `tasks daemon stop` sends, so it is the one exit the agent asked
        # for; every other way out of the loop below is news the agent needs.
        nonlocal shutdown_reason, asked_to_stop
        shutdown_reason = signal.Signals(signum).name
        asked_to_stop = signum == signal.SIGTERM
        raise SystemExit(0)

    # Installed before anything is brought up, so a signal arriving during startup is answered.
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    http_server = start_server(config, port, notif_dir)

    tick_interval = int(os.environ["TASKS_SYNC_INTERVAL"]) if "TASKS_SYNC_INTERVAL" in os.environ else 5

    print(json.dumps({"status": "serving", "tick_interval": tick_interval, "http_port": port}))
    sys.stdout.flush()
    try:
        while True:
            time.sleep(tick_interval)
            try:
                commands.fire_due_checkpoints(config, notif_dir)
                commands.maybe_send_digest(config, notif_dir)
            except Exception:
                # A bad tick (locked db, malformed row) must not kill the daemon; retry next tick.
                logging.getLogger(__name__).exception("serve tick failed")
    finally:
        http_server.should_exit = True
        if not asked_to_stop:
            write_notification(notif_dir, "daemon_died", reason=shutdown_reason)
