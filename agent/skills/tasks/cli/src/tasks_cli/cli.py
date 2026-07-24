import argparse
import json
import logging
import os
import signal
import sys
import time
from contextlib import closing, suppress
from pathlib import Path

from . import commands, db
from . import format as fmt
from .config import Config
from .scheduler import create_scheduler, write_notification


def _add_format_flags(parser: argparse.ArgumentParser) -> None:
    """Attach mutually-exclusive --json / --json-pretty flags to a list-style subparser."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true", help="Emit compact JSON instead of a table.")
    group.add_argument("--json-pretty", action="store_true", help="Emit indented JSON instead of a table.")


def _write_pid(config):
    (config.data_dir / "serve.pid").write_text(str(os.getpid()))


def _remove_pid(config):
    with suppress(FileNotFoundError):
        (config.data_dir / "serve.pid").unlink()


def _fail_daemon_not_running(detail: str):
    msg = f"daemon not running{detail} — start with: screen -dmS tasks tasks serve --notifications-dir ~/agent/notifications"
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(1)


def _require_arg(value: str | None, name: str, usage: str) -> str:
    if not value:
        raise ValueError(f"{name} is required: {usage}")
    return value


def _require_daemon(config):
    pid_file = config.data_dir / "serve.pid"
    if not pid_file.exists():
        _fail_daemon_not_running("")
    try:
        os.kill(int(pid_file.read_text().strip()), 0)
    except (ValueError, ProcessLookupError, OSError):
        pid_file.unlink(missing_ok=True)
        _fail_daemon_not_running(" (stale pid file)")


def _sync_jobs(config: Config, scheduler, notif_dir: Path):
    """Sync scheduler jobs with DB state: remove stale, add new, re-add moved one-shots (snooze)."""
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT id, scheduled_time, trigger_data FROM reminders WHERE completed = 0 AND trigger_data IS NOT NULL")
        rows = {row["id"]: (row["scheduled_time"], row["trigger_data"]) for row in cursor}

    jobs = {job.id: job for job in scheduler.get_jobs()}
    for sid in set(jobs) - set(rows):
        try:
            scheduler.remove_job(sid)
        except Exception as e:
            logging.getLogger(__name__).warning("Failed to remove stale job %s: %s", sid, e)

    to_restore = set(rows) - set(jobs)
    for jid, (scheduled_time, trigger_data) in rows.items():
        if jid not in jobs or scheduled_time is None or jobs[jid].next_run_time is None:
            continue
        if abs((jobs[jid].next_run_time - db.parse_datetime(scheduled_time)).total_seconds()) <= commands.STALE_FIRE_SLACK.total_seconds():
            continue
        # Only one-shot ("date") triggers move underneath a live job (remind snooze rewrites them
        # in place); recurring jobs recompute their own next fire and must not be reset here.
        data = json.loads(trigger_data)
        if "type" in data and data["type"] == "date":
            to_restore.add(jid)
    if to_restore:
        commands.restore_jobs_by_ids(config, scheduler, to_restore, notif_dir=notif_dir)


def _add_id_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("id_pos", nargs="?", default=None, metavar="id")
    parser.add_argument("--id", default=None, dest="task_id")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tasks")
    sub = parser.add_subparsers(dest="command", required=True)

    # serve
    p_serve = sub.add_parser("serve", help="Run background daemon (scheduler + reminder engine)")
    p_serve.add_argument("--notifications-dir", default=str(Path.home() / "agent" / "notifications"))
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
    p_update.add_argument("--status", default=None)
    p_update.add_argument("--title", default=None)
    p_update.add_argument("--priority", default=None)
    p_update.add_argument("--due-datetime", default=None)
    p_update.add_argument("--timezone", default=None)
    p_update.add_argument("--due-in-minutes", type=int, default=None)
    p_update.add_argument("--due-in-hours", type=int, default=None)
    p_update.add_argument("--due-in-days", type=int, default=None)

    # done
    p_done = sub.add_parser("done", help="Mark a task done")
    _add_id_args(p_done)

    # postpone
    p_postpone = sub.add_parser("postpone", help="Set a new due date measured from now (also gives undated tasks one)")
    _add_id_args(p_postpone)
    p_postpone.add_argument("--in-minutes", type=int, default=None)
    p_postpone.add_argument("--in-hours", type=int, default=None)
    p_postpone.add_argument("--in-days", type=int, default=None)
    p_postpone.add_argument("--at", default=None)
    p_postpone.add_argument("--tz", default=None)

    # delete
    p_delete = sub.add_parser("delete", help="Delete a task")
    _add_id_args(p_delete)

    # search
    p_search = sub.add_parser("search", help="Search tasks by title")
    p_search.add_argument("query_pos", nargs="?", default=None, metavar="query")
    p_search.add_argument("--query", default=None)
    p_search.add_argument("--show-completed", action="store_true")
    _add_format_flags(p_search)

    # remind (placeholder for --help)
    sub.add_parser("remind", help="Set, list, delete, or update reminders")

    return parser


def main():
    # We manually handle `tasks remind ...` because argparse cannot mix
    # positional arguments with subparsers on the same parser level.
    # Everything else goes through standard argparse.

    if len(sys.argv) >= 2 and sys.argv[1] == "remind":
        return _main_remind()

    args = _build_parser().parse_args()
    config = Config()

    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)

    db.init_db(config.data_dir)

    try:
        if args.command == "serve":
            _run_serve(config, Path(args.notifications_dir), port=args.port)
            return None

        _require_daemon(config)
        _handle_task(args, config)

    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


def _remind_list_cmd(config: Config, argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="tasks remind list", add_help=False)
    p.add_argument("--task", default=None, dest="task_id")
    p.add_argument("--limit", type=int, default=50)
    _add_format_flags(p)
    args = p.parse_args(argv)
    _print_list(args, commands.remind_list(config, task_id=args.task_id, limit=args.limit), fmt.format_reminder_list)


def _remind_delete_cmd(config: Config, argv: list[str]) -> dict:
    p = argparse.ArgumentParser(prog="tasks remind delete", add_help=False)
    p.add_argument("id_pos", nargs="?", default=None, metavar="id")
    p.add_argument("--id", default=None, dest="reminder_id")
    args = p.parse_args(argv)
    reminder_id = _require_arg(args.id_pos or args.reminder_id, "id", "tasks remind delete <id> or tasks remind delete --id <id>")
    return commands.remind_delete(config, reminder_id=reminder_id)


def _remind_update_cmd(config: Config, argv: list[str]) -> dict:
    p = argparse.ArgumentParser(prog="tasks remind update", add_help=False)
    p.add_argument("id_pos", nargs="?", default=None, metavar="id")
    p.add_argument("--id", default=None, dest="reminder_id")
    p.add_argument("--message", required=True)
    args = p.parse_args(argv)
    reminder_id = _require_arg(args.id_pos or args.reminder_id, "id", "tasks remind update <id> or tasks remind update --id <id>")
    return commands.remind_update(config, reminder_id=reminder_id, message=args.message)


def _remind_snooze_cmd(config: Config, argv: list[str]) -> dict:
    p = argparse.ArgumentParser(prog="tasks remind snooze", add_help=False)
    p.add_argument("id_pos", nargs="?", default=None, metavar="id")
    p.add_argument("--id", default=None, dest="reminder_id")
    p.add_argument("--in-minutes", type=int, default=None)
    p.add_argument("--in-hours", type=int, default=None)
    p.add_argument("--in-days", type=int, default=None)
    p.add_argument("--at", default=None)
    p.add_argument("--tz", default=None)
    args = p.parse_args(argv)
    reminder_id = _require_arg(args.id_pos or args.reminder_id, "id", "tasks remind snooze <id> --in-hours N")
    return commands.remind_snooze(
        config,
        reminder_id=reminder_id,
        in_minutes=args.in_minutes,
        in_hours=args.in_hours,
        in_days=args.in_days,
        at=args.at,
        tz=args.tz,
    )


def _remind_set_cmd(config: Config, argv: list[str]) -> dict:
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
    p.add_argument("--cron", default=None)
    p.add_argument("--fuzz-minutes", type=int, default=None)
    args = p.parse_args(argv)
    message = _require_arg(args.message_pos or args.message, "message", 'tasks remind "message" or tasks remind --message "message"')
    return commands.remind_set(
        config,
        commands.ReminderSpec(
            message=message,
            task_id=args.task_id,
            scheduled_datetime=args.scheduled_datetime,
            tz=args.tz,
            in_minutes=args.in_minutes,
            in_hours=args.in_hours,
            in_days=args.in_days,
            recurring=args.recurring,
            cron=args.cron,
            fuzz_minutes=args.fuzz_minutes,
        ),
    )


def _main_remind():
    """Handle all `tasks remind ...` commands with manual dispatch."""
    config = Config()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    db.init_db(config.data_dir)

    remind_args = sys.argv[2:]

    if not remind_args or remind_args in (["-h"], ["--help"]):
        _print_remind_help()
        return

    subcmd = remind_args[0]
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

        if subcmd == "list":
            _remind_list_cmd(config, remind_args[1:])
            return
        if subcmd == "delete":
            result = _remind_delete_cmd(config, remind_args[1:])
        elif subcmd == "update":
            result = _remind_update_cmd(config, remind_args[1:])
        elif subcmd == "snooze":
            result = _remind_snooze_cmd(config, remind_args[1:])
        else:
            result = _remind_set_cmd(config, remind_args)

        print(json.dumps(result, indent=2))

    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


def _print_remind_help():
    print("""usage: tasks remind <message> [options]
       tasks remind list [--task <id>] [--limit N]
       tasks remind snooze <id> --in-hours N
       tasks remind delete <id>
       tasks remind update <id> --message <msg>

Set a reminder (default):
  tasks remind "call mom" --in-minutes 30
  tasks remind "check this" --task <id> --at <datetime> --tz <tz>
  tasks remind "standup" --recurring daily --at <datetime> --tz <tz>
  tasks remind "wind down" --recurring daily --at <datetime> --tz <tz> --fuzz-minutes 75
  tasks remind "weekdays 9am" --cron "0 9 * * 1-5" --tz <tz>

options:
  --message MSG         Message (alternative to positional)
  --task ID             Link to a task
  --at DATETIME         Scheduled datetime (ISO-8601)
  --tz TZ               Timezone (IANA name)
  --in-minutes N        Fire in N minutes
  --in-hours N          Fire in N hours
  --in-days N           Fire in N days
  --recurring TYPE      hourly|daily|weekly|monthly|yearly
  --cron EXPR           Standard 5-field cron "min hour dom month dow" (requires --tz)
  --fuzz-minutes N      Recurring/cron only: each fire lands within +/-N minutes of the nominal time

subcommands:
  list                  List active reminders
  snooze                Push a one-shot reminder back (works on fired ones too)
  delete                Delete a reminder
  update                Update a reminder message""")


def _handle_task(args, config: Config):
    if args.command == "add":
        title = _require_arg(args.title_pos or args.title, "title", 'tasks add "title" or tasks add --title "title"')
        result = commands.add_task(
            config,
            title=title,
            due=commands.DueSpec(
                due_datetime=args.due_datetime,
                timezone=args.timezone,
                due_in_minutes=args.due_in_minutes,
                due_in_hours=args.due_in_hours,
                due_in_days=args.due_in_days,
            ),
            priority=args.priority,
            initial_metadata=args.initial_metadata,
        )
        print(json.dumps(result, indent=2))
        return
    if args.command == "list":
        _print_list(args, commands.list_tasks(config, show_completed=args.show_completed), fmt.format_task_list)
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
        result = commands.update_task(
            config,
            task_id=task_id,
            status=args.status,
            title=args.title,
            priority=args.priority,
            due=commands.DueSpec(
                due_datetime=args.due_datetime,
                timezone=args.timezone,
                due_in_minutes=args.due_in_minutes,
                due_in_hours=args.due_in_hours,
                due_in_days=args.due_in_days,
            ),
        )
    elif args.command == "done":
        task_id = _require_arg(args.id_pos or args.task_id, "id", "tasks done <id> or tasks done --id <id>")
        result = commands.update_task(config, task_id=task_id, status="done")
    elif args.command == "postpone":
        task_id = _require_arg(args.id_pos or args.task_id, "id", "tasks postpone <id> --in-days N")
        result = commands.postpone_task(
            config,
            task_id=task_id,
            due_datetime=args.at,
            timezone=args.tz,
            in_minutes=args.in_minutes,
            in_hours=args.in_hours,
            in_days=args.in_days,
        )
    elif args.command == "delete":
        task_id = _require_arg(args.id_pos or args.task_id, "id", "tasks delete <id> or tasks delete --id <id>")
        result = commands.delete_task(config, task_id=task_id)
    elif args.command == "search":
        query = _require_arg(args.query_pos or args.query, "query", 'tasks search "query" or tasks search --query "query"')
        _print_list(args, commands.search_tasks(config, query=query, show_completed=args.show_completed), fmt.format_task_list)
        return
    else:
        return

    print(json.dumps(result, indent=2))


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

    http_server = start_server(config, port)

    scheduler = create_scheduler()
    scheduler.start()
    commands.restore_all_jobs(config, scheduler, notif_dir=notif_dir)
    stop = False
    shutdown_reason = "unknown"

    def handle_signal(signum, _frame):
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
            try:
                _sync_jobs(config, scheduler, notif_dir)
                commands.maybe_send_digest(config, notif_dir)
            except Exception:
                # A bad tick (locked db, malformed row) must not kill the daemon; retry next tick.
                logging.getLogger(__name__).exception("serve tick failed")
    finally:
        http_server.should_exit = True
        write_notification(notif_dir, "daemon_died", reason=shutdown_reason)
        _remove_pid(config)
        scheduler.shutdown(wait=True)
