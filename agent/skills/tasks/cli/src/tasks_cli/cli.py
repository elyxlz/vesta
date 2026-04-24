import argparse
import json
import logging
import os
import signal
import sys
import time
from contextlib import closing
from datetime import datetime, UTC
from pathlib import Path

from .config import Config
from . import commands, db, format as fmt
from .scheduler import create_scheduler


def _add_format_flags(parser: argparse.ArgumentParser) -> None:
    """Attach mutually-exclusive --json / --json-pretty flags to a list-style subparser."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true", help="Emit compact JSON instead of a table.")
    group.add_argument("--json-pretty", action="store_true", help="Emit indented JSON instead of a table.")


def _write_pid(config):
    (config.data_dir / "serve.pid").write_text(str(os.getpid()))


def _remove_pid(config):
    try:
        (config.data_dir / "serve.pid").unlink()
    except FileNotFoundError:
        pass


def _write_death_notification(notif_dir: Path, reason: str):
    notif_dir.mkdir(exist_ok=True)
    notif = {"timestamp": datetime.now(UTC).isoformat(), "source": "tasks", "type": "daemon_died", "reason": reason}
    filename = f"{int(time.time() * 1e6)}-tasks-daemon_died.json"
    tmp = notif_dir / f"{filename}.tmp"
    tmp.write_text(json.dumps(notif))
    os.replace(tmp, notif_dir / filename)


def _require_daemon(config):
    pid_file = config.data_dir / "serve.pid"
    if not pid_file.exists():
        print(
            json.dumps({"error": "daemon not running — start with: screen -dmS tasks tasks serve --notifications-dir ~/agent/notifications"}),
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        os.kill(int(pid_file.read_text().strip()), 0)
    except (ValueError, ProcessLookupError, OSError):
        pid_file.unlink(missing_ok=True)
        print(
            json.dumps(
                {
                    "error": "daemon not running (stale pid file) — start with: screen -dmS tasks tasks serve --notifications-dir ~/agent/notifications"
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)


def _sync_jobs(config: Config, scheduler, notif_dir: Path):
    """Sync scheduler jobs with DB state: remove stale, add new."""
    scheduled_ids = {job.id for job in scheduler.get_jobs()}

    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT id FROM reminders WHERE completed = 0 AND trigger_data IS NOT NULL")
        db_ids = {row["id"] for row in cursor}

    for sid in scheduled_ids - db_ids:
        try:
            scheduler.remove_job(sid)
        except Exception as e:
            logging.getLogger(__name__).warning(f"Failed to remove stale job {sid}: {e}")

    missing = db_ids - scheduled_ids
    if missing:
        commands.restore_jobs_by_ids(config, scheduler, missing, notif_dir=notif_dir)


def _build_remind_set_parser():
    """Build the parser for `tasks remind <message> [options]`."""
    p = argparse.ArgumentParser(prog="tasks remind", add_help=False)
    p.add_argument("message_pos", nargs="?", default=None, metavar="message")
    p.add_argument("--message", default=None)
    p.add_argument("--task", default=None, dest="task_id")
    p.add_argument("--at", default=None, dest="scheduled_datetime")
    p.add_argument("--tz", default=None)
    p.add_argument("--in-minutes", type=int, default=None)
    p.add_argument("--in-hours", type=int, default=None)
    p.add_argument("--in-days", type=int, default=None)
    p.add_argument("--recurring", default=None, choices=["hourly", "daily", "weekly", "monthly", "yearly"])
    return p


def _build_remind_list_parser():
    p = argparse.ArgumentParser(prog="tasks remind list", add_help=False)
    p.add_argument("--task", default=None, dest="task_id")
    p.add_argument("--limit", type=int, default=50)
    _add_format_flags(p)
    return p


def _build_remind_delete_parser():
    p = argparse.ArgumentParser(prog="tasks remind delete", add_help=False)
    p.add_argument("id_pos", nargs="?", default=None, metavar="id")
    p.add_argument("--id", default=None, dest="reminder_id")
    return p


def _build_remind_update_parser():
    p = argparse.ArgumentParser(prog="tasks remind update", add_help=False)
    p.add_argument("id_pos", nargs="?", default=None, metavar="id")
    p.add_argument("--id", default=None, dest="reminder_id")
    p.add_argument("--message", required=True)
    return p


def main():
    # We manually handle `tasks remind ...` because argparse cannot mix
    # positional arguments with subparsers on the same parser level.
    # Everything else goes through standard argparse.

    if len(sys.argv) >= 2 and sys.argv[1] == "remind":
        return _main_remind()

    parser = argparse.ArgumentParser(prog="tasks")
    sub = parser.add_subparsers(dest="command", required=True)

    # serve
    p_serve = sub.add_parser("serve", help="Run background daemon (scheduler + reminder engine)")
    p_serve.add_argument("--notifications-dir", required=True)
    p_serve.add_argument("--port", type=int, required=True, help="HTTP server port (allocated by vestad)")

    # add
    p_add = sub.add_parser("add", help="Add a new task")
    p_add.add_argument("title_pos", nargs="?", default=None, metavar="title")
    p_add.add_argument("--title", default=None)
    p_add.add_argument("--due-datetime", default=None)
    p_add.add_argument("--timezone", default=None)
    p_add.add_argument("--due-in-minutes", type=int, default=None)
    p_add.add_argument("--due-in-hours", type=int, default=None)
    p_add.add_argument("--due-in-days", type=int, default=None)
    p_add.add_argument("--priority", default="normal", help="low/normal/high or 1/2/3")
    p_add.add_argument("--initial-metadata", default=None)

    # list
    p_list = sub.add_parser("list", help="List tasks")
    p_list.add_argument("--show-completed", action="store_true")
    _add_format_flags(p_list)

    # get
    p_get = sub.add_parser("get", help="Get a task by ID")
    p_get.add_argument("id_pos", nargs="?", default=None, metavar="id")
    p_get.add_argument("--id", default=None, dest="task_id")
    p_get.add_argument(
        "--field",
        action="append",
        default=None,
        choices=list(commands.TASK_FIELDS),
        help="Return only the named field(s). Repeat for multiple. Skips reading metadata unless --field metadata.",
    )

    # update
    p_update = sub.add_parser("update", help="Update a task")
    p_update.add_argument("id_pos", nargs="?", default=None, metavar="id")
    p_update.add_argument("--id", default=None, dest="task_id")
    p_update.add_argument("--status", default=None)
    p_update.add_argument("--title", default=None)
    p_update.add_argument("--priority", default=None)
    p_update.add_argument("--due-datetime", default=None)
    p_update.add_argument("--timezone", default=None)
    p_update.add_argument("--due-in-minutes", type=int, default=None)
    p_update.add_argument("--due-in-hours", type=int, default=None)
    p_update.add_argument("--due-in-days", type=int, default=None)

    # delete
    p_delete = sub.add_parser("delete", help="Delete a task")
    p_delete.add_argument("id_pos", nargs="?", default=None, metavar="id")
    p_delete.add_argument("--id", default=None, dest="task_id")

    # search
    p_search = sub.add_parser("search", help="Search tasks by title")
    p_search.add_argument("query_pos", nargs="?", default=None, metavar="query")
    p_search.add_argument("--query", default=None)
    p_search.add_argument("--show-completed", action="store_true")
    _add_format_flags(p_search)

    # remind (placeholder for --help)
    sub.add_parser("remind", help="Set, list, delete, or update reminders")

    args = parser.parse_args()
    config = Config()

    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)

    db.init_db(config.data_dir)

    try:
        if args.command == "serve":
            _run_serve(config, Path(args.notifications_dir), port=args.port)
            return

        _require_daemon(config)
        _handle_task(args, config)

    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


def _main_remind():
    """Handle all `tasks remind ...` commands with manual dispatch."""
    config = Config()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    db.init_db(config.data_dir)

    remind_args = sys.argv[2:]

    if not remind_args or remind_args == ["-h"] or remind_args == ["--help"]:
        _print_remind_help()
        return

    subcmd = remind_args[0]
    subcommands = {"list", "delete", "update"}
    # Reject common false-subcommands that would silently become the message
    rejected = {"create", "add", "new", "set", "get", "show"}
    if subcmd in rejected:
        print(
            f'Error: "{subcmd}" is not a valid subcommand. To set a reminder, use: tasks remind "your message" [options]',
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        _require_daemon(config)

        if subcmd in subcommands:
            rest = remind_args[1:]

            if subcmd == "list":
                args = _build_remind_list_parser().parse_args(rest)
                result = _do_remind_list(config, args)
                _print_reminder_list_result(args, result)
                return
            elif subcmd == "delete":
                args = _build_remind_delete_parser().parse_args(rest)
                result = _do_remind_delete(config, args)
            elif subcmd == "update":
                args = _build_remind_update_parser().parse_args(rest)
                result = _do_remind_update(config, args)
        else:
            args = _build_remind_set_parser().parse_args(remind_args)
            result = _do_remind_set(config, args)

        print(json.dumps(result, indent=2))

    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


def _print_remind_help():
    print("""usage: tasks remind <message> [options]
       tasks remind list [--task <id>] [--limit N]
       tasks remind delete <id>
       tasks remind update <id> --message <msg>

Set a reminder (default):
  tasks remind "call mom" --in-minutes 30
  tasks remind "check this" --task <id> --at <datetime> --tz <tz>
  tasks remind "standup" --recurring daily --at <datetime> --tz <tz>

options:
  --message MSG         Message (alternative to positional)
  --task ID             Link to a task
  --at DATETIME         Scheduled datetime (ISO-8601)
  --tz TZ               Timezone (IANA name)
  --in-minutes N        Fire in N minutes
  --in-hours N          Fire in N hours
  --in-days N           Fire in N days
  --recurring TYPE      hourly|daily|weekly|monthly|yearly

subcommands:
  list                  List active reminders
  delete                Delete a reminder
  update                Update a reminder message""")


def _do_remind_set(config, args):
    message = args.message_pos or args.message
    if not message:
        raise ValueError('message is required: tasks remind "message" or tasks remind --message "message"')
    return commands.remind_set(
        config,
        message=message,
        task_id=args.task_id,
        scheduled_datetime=args.scheduled_datetime,
        tz=args.tz,
        in_minutes=args.in_minutes,
        in_hours=args.in_hours,
        in_days=args.in_days,
        recurring=args.recurring,
    )


def _do_remind_list(config, args):
    return commands.remind_list(config, task_id=args.task_id, limit=args.limit)


def _do_remind_delete(config, args):
    reminder_id = args.id_pos or args.reminder_id
    if not reminder_id:
        raise ValueError("id is required: tasks remind delete <id> or tasks remind delete --id <id>")
    return commands.remind_delete(config, reminder_id=reminder_id)


def _do_remind_update(config, args):
    reminder_id = args.id_pos or args.reminder_id
    if not reminder_id:
        raise ValueError("id is required: tasks remind update <id> or tasks remind update --id <id>")
    return commands.remind_update(config, reminder_id=reminder_id, message=args.message)


def _handle_task(args, config: Config):
    if args.command == "add":
        title = args.title_pos or args.title
        if not title:
            raise ValueError('title is required: tasks add "title" or tasks add --title "title"')
        result = commands.add_task(
            config,
            title=title,
            due_datetime=args.due_datetime,
            timezone=args.timezone,
            due_in_minutes=args.due_in_minutes,
            due_in_hours=args.due_in_hours,
            due_in_days=args.due_in_days,
            priority=args.priority,
            initial_metadata=args.initial_metadata,
        )
        print(json.dumps(result, indent=2))
        return
    elif args.command == "list":
        result = commands.list_tasks(config, show_completed=args.show_completed)
        _print_task_list_result(args, result)
        return
    elif args.command == "get":
        task_id = args.id_pos or args.task_id
        if not task_id:
            raise ValueError("id is required: tasks get <id> or tasks get --id <id>")
        if args.field:
            fields = list(args.field)
            result = commands.get_task_fields(config, task_id=task_id, fields=fields)
            _print_get_field_result(fields, result)
            return
        result = commands.get_task(config, task_id=task_id)
    elif args.command == "update":
        task_id = args.id_pos or args.task_id
        if not task_id:
            raise ValueError("id is required: tasks update <id> or tasks update --id <id>")
        result = commands.update_task(
            config,
            task_id=task_id,
            status=args.status,
            title=args.title,
            priority=args.priority,
            due_datetime=args.due_datetime,
            timezone=args.timezone,
            due_in_minutes=args.due_in_minutes,
            due_in_hours=args.due_in_hours,
            due_in_days=args.due_in_days,
        )
    elif args.command == "delete":
        task_id = args.id_pos or args.task_id
        if not task_id:
            raise ValueError("id is required: tasks delete <id> or tasks delete --id <id>")
        result = commands.delete_task(config, task_id=task_id)
    elif args.command == "search":
        query = args.query_pos or args.query
        if not query:
            raise ValueError('query is required: tasks search "query" or tasks search --query "query"')
        result = commands.search_tasks(config, query=query, show_completed=args.show_completed)
        _print_task_list_result(args, result)
        return
    else:
        return

    print(json.dumps(result, indent=2))


def _format_flags(args) -> tuple[bool, bool]:
    """Return (want_compact_json, want_pretty_json) based on argparse args."""
    attrs = vars(args)
    return (
        "json" in attrs and attrs["json"],
        "json_pretty" in attrs and attrs["json_pretty"],
    )


def _print_task_list_result(args, result: list) -> None:
    want_json, want_pretty = _format_flags(args)
    if want_pretty:
        print(json.dumps(result, indent=2))
        return
    if want_json:
        print(json.dumps(result))
        return
    print(fmt.format_task_list(result))


def _print_reminder_list_result(args, result: list) -> None:
    want_json, want_pretty = _format_flags(args)
    if want_pretty:
        print(json.dumps(result, indent=2))
        return
    if want_json:
        print(json.dumps(result))
        return
    print(fmt.format_reminder_list(result))


def _print_get_field_result(fields: list[str], result: dict) -> None:
    """Print raw field values when --field is given. Single field: raw value. Multiple: tab-separated."""
    values = []
    for f in fields:
        v = result[f] if f in result else ""
        values.append("" if v is None else str(v))
    if len(values) == 1:
        print(values[0])
    else:
        print("\t".join(values))


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

    http_server = start_server(config, port)

    scheduler = create_scheduler()
    scheduler.start()
    commands.restore_all_jobs(config, scheduler, notif_dir=notif_dir)
    stop = False
    shutdown_reason = "unknown"

    def handle_signal(signum, frame):
        nonlocal stop, shutdown_reason
        shutdown_reason = signal.Signals(signum).name
        stop = True

    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    sync_interval = int(os.environ["TASKS_SYNC_INTERVAL"]) if "TASKS_SYNC_INTERVAL" in os.environ else 5

    _write_pid(config)

    print(json.dumps({"status": "serving", "sync_interval": sync_interval, "http_port": port}))
    sys.stdout.flush()
    try:
        while not stop:
            time.sleep(sync_interval)
            _sync_jobs(config, scheduler, notif_dir)
    finally:
        http_server.should_exit = True
        _write_death_notification(notif_dir, shutdown_reason)
        _remove_pid(config)
        scheduler.shutdown(wait=True)
