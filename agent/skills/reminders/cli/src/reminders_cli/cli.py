import argparse
import json
import logging
import os
import signal
import sys
import time
from contextlib import closing
from pathlib import Path

from . import commands, daemon, db
from . import format as fmt
from .config import Config
from .scheduler import create_scheduler, write_notification


def _add_format_flags(parser: argparse.ArgumentParser) -> None:
    """Attach mutually-exclusive --json / --json-pretty flags to a list-style subparser."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true", help="Emit compact JSON instead of a table.")
    group.add_argument("--json-pretty", action="store_true", help="Emit indented JSON instead of a table.")


def _add_id_args(parser: argparse.ArgumentParser) -> None:
    """The reminder id, as a positional or --id."""
    parser.add_argument("id_pos", nargs="?", default=None, metavar="id")
    parser.add_argument("--id", default=None, dest="reminder_id")


def _require_arg(value: str | None, name: str, usage: str) -> str:
    if not value:
        raise ValueError(f"{name} is required: {usage}")
    return value


def _require_daemon():
    if daemon.live_pid() is None:
        msg = "daemon not running, start it with: reminders daemon start"
        print(json.dumps({"error": msg}), file=sys.stderr)
        sys.exit(1)


def _sync_jobs(config: Config, scheduler, notif_dir: Path):
    """Sync scheduler jobs with DB state: remove stale, add new, re-add moved one-shots (snooze)."""
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute(f"SELECT id, scheduled_time, trigger_data FROM reminders WHERE {commands.LIVE_REMINDER}")
        rows = {row["id"]: (row["scheduled_time"], row["trigger_data"]) for row in cursor}

    jobs = {job.id: job for job in scheduler.get_jobs()}
    for sid in set(jobs) - set(rows):
        try:
            scheduler.remove_job(sid)
        except Exception as e:
            logging.getLogger(__name__).warning("Failed to remove stale job %s: %s", sid, e)

    to_restore = set(rows) - set(jobs)
    for jid, (scheduled_time, trigger_data) in rows.items():
        if jid not in jobs:
            continue
        data = json.loads(trigger_data)
        if commands.cron_zone_moved(jobs[jid], data):
            to_restore.add(jid)
            continue
        if scheduled_time is None or jobs[jid].next_run_time is None:
            continue
        if abs((jobs[jid].next_run_time - db.parse_datetime(scheduled_time)).total_seconds()) <= commands.STALE_FIRE_SLACK.total_seconds():
            continue
        # Only a one-shot job moves underneath a live job: a snoozed "date" row, or the chained fire
        # of a fuzzed cron row. A plain cron job recomputes its own next fire and is not reset here.
        if "type" in data and (data["type"] == "date" or "fuzz_minutes" in data):
            to_restore.add(jid)
    if to_restore:
        commands.restore_jobs_by_ids(config, scheduler, to_restore, notif_dir=notif_dir)


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] == "help" or argv in (["-h"], ["--help"]):
        _print_help()
        return

    config = Config()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    db.init_db(config.data_dir)

    cmd = argv[0]

    if cmd == "serve":
        _serve_cmd(config, argv[1:])
        return
    if cmd == "daemon":
        action = argv[1] if len(argv) > 1 else ""
        sys.exit(daemon.daemon_cmd(action))

    try:
        _require_daemon()

        if cmd == "list":
            _list_cmd(config, argv[1:])
            return
        if cmd == "get":
            _get_cmd(config, argv[1:])
            return
        if cmd == "create":
            result = _create_cmd(config, argv[1:])
        elif cmd == "delete":
            result = _delete_cmd(config, argv[1:])
        elif cmd == "update":
            result = _update_cmd(config, argv[1:])
        elif cmd == "snooze":
            result = _snooze_cmd(config, argv[1:])
        else:
            print(json.dumps({"error": f'"{cmd}" is not a subcommand. Set one with: reminders create "message" [options]'}), file=sys.stderr)
            sys.exit(1)

        print(json.dumps(result, indent=2))

    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


REMIND_LIST_PAGE_SIZE = 50


def _list_cmd(config: Config, argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="reminders list")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--show-completed", action="store_true")
    p.add_argument("--show-deleted", action="store_true")
    _add_format_flags(p)
    args = p.parse_args(argv)
    # JSON is consumed by scripts asking absence questions ("is anything scheduled for X?"), so a
    # silent page size would make a truncated list read as "no": JSON and an explicit --limit get
    # exactly what they asked for. The table fetches everything and pages here, so it can say how
    # many rows it held back, on stderr so a stdout pipe (grep, head) can never eat the notice.
    paged = args.limit is None and not (args.json or args.json_pretty)
    reminders = commands.remind_list(config, limit=args.limit, show_completed=args.show_completed, show_deleted=args.show_deleted)
    held_back = len(reminders) - REMIND_LIST_PAGE_SIZE if paged else 0
    shown = reminders[:REMIND_LIST_PAGE_SIZE] if paged else reminders
    if args.json_pretty:
        print(json.dumps(shown, indent=2))
    elif args.json:
        print(json.dumps(shown))
    else:
        print(fmt.format_reminder_list(shown))
    if held_back > 0:
        print(f"... showing {REMIND_LIST_PAGE_SIZE} of {len(reminders)}. Use --limit <n> or --json to see them all.", file=sys.stderr)


def _get_cmd(config: Config, argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="reminders get")
    _add_id_args(p)
    p.add_argument(
        "--field",
        action="append",
        default=None,
        choices=list(commands.REMINDER_FIELDS),
        help="Return only the named field(s). Repeat for multiple.",
    )
    args = p.parse_args(argv)
    reminder_id = _require_arg(args.id_pos or args.reminder_id, "id", "reminders get <id> or reminders get --id <id>")
    result = commands.remind_get(config, reminder_id=reminder_id)
    if args.field:
        # Raw field values: one field prints the value alone; multiple are tab-separated.
        values = ["" if result[f] is None else str(result[f]) for f in args.field]
        print(values[0] if len(values) == 1 else "\t".join(values))
        return
    print(json.dumps(result, indent=2))


def _delete_cmd(config: Config, argv: list[str]) -> dict:
    p = argparse.ArgumentParser(prog="reminders delete")
    _add_id_args(p)
    args = p.parse_args(argv)
    reminder_id = _require_arg(args.id_pos or args.reminder_id, "id", "reminders delete <id> or reminders delete --id <id>")
    return commands.remind_delete(config, reminder_id=reminder_id)


def _update_cmd(config: Config, argv: list[str]) -> dict:
    p = argparse.ArgumentParser(prog="reminders update")
    _add_id_args(p)
    p.add_argument("--message", default=None)
    p.add_argument("--tz", default=None, help="Repoint a recurring schedule to this IANA zone, keeping its wall-clock time")
    p.add_argument("--unpin-tz", action="store_true", help="Drop the pinned zone, so the schedule follows the agent's own timezone")
    args = p.parse_args(argv)
    reminder_id = _require_arg(args.id_pos or args.reminder_id, "id", "reminders update <id> --message <msg> (or --tz <zone>)")
    spec = commands.UpdateSpec(message=args.message, tz=args.tz, unpin_tz=args.unpin_tz)
    return commands.remind_update(config, reminder_id=reminder_id, spec=spec)


def _snooze_cmd(config: Config, argv: list[str]) -> dict:
    p = argparse.ArgumentParser(prog="reminders snooze")
    _add_id_args(p)
    p.add_argument("--in-minutes", type=int, default=None, help="Fire N minutes from now")
    p.add_argument("--in-hours", type=int, default=None, help="Fire N hours from now")
    p.add_argument("--in-days", type=int, default=None, help="Fire N days from now")
    p.add_argument("--at", default=None, help="Fire at this datetime (ISO-8601, in the agent's own timezone unless --tz names one)")
    p.add_argument("--tz", default=None, help="IANA timezone for --at; omit to use the agent's own timezone")
    args = p.parse_args(argv)
    reminder_id = _require_arg(args.id_pos or args.reminder_id, "id", "reminders snooze <id> --in-hours N (or --at <iso> [--tz <tz>])")
    spec = commands.SnoozeSpec(
        in_minutes=args.in_minutes,
        in_hours=args.in_hours,
        in_days=args.in_days,
        at=args.at,
        tz=args.tz,
    )
    return commands.remind_snooze(config, reminder_id=reminder_id, spec=spec)


def _create_cmd(config: Config, argv: list[str]) -> dict:
    p = argparse.ArgumentParser(prog="reminders create")
    p.add_argument("message_pos", nargs="?", default=None, metavar="message")
    p.add_argument("--message", default=None)
    p.add_argument("--at", default=None, dest="scheduled_datetime")
    tz_help = "IANA timezone; omit to use the agent's own timezone, pass one only to pin the schedule to that zone"
    p.add_argument("--tz", default=None, help=tz_help)
    p.add_argument("--in-minutes", type=int, default=None)
    p.add_argument("--in-hours", type=int, default=None)
    p.add_argument("--in-days", type=int, default=None)
    p.add_argument("--recurring", default=None, choices=["hourly", "daily", "weekly", "monthly", "yearly"])
    p.add_argument("--cron", default=None)
    p.add_argument("--fuzz-minutes", type=int, default=None)
    args = p.parse_args(argv)
    message = _require_arg(args.message_pos or args.message, "message", 'reminders create "message" or reminders create --message "message"')
    return commands.remind_set(
        config,
        commands.ReminderSpec(
            message=message,
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


def _print_help():
    print("""usage: reminders create <message> [options]
       reminders list [--limit N] [--show-completed] [--show-deleted]
       reminders get <id> [--field <name>]
       reminders snooze <id> --in-hours N | --at <iso> [--tz <tz>]
       reminders delete <id>
       reminders update <id> --message <msg> | --tz <zone> | --unpin-tz

Create a reminder:
  reminders create "call mom" --in-minutes 30
  reminders create "event" --at <datetime>
  reminders create "standup" --recurring daily --at 09:30
  reminders create "wind down" --recurring daily --at 21:30 --fuzz-minutes 75
  reminders create "weekdays 9am" --cron "0 9 * * 1-5"
  reminders create "market open" --recurring daily --at 09:30 --tz America/New_York   # --tz pins the zone

create options:
  --message MSG         Message (alternative to positional)
  --at DATETIME         Scheduled datetime (ISO-8601; a bare HH:MM works with --recurring daily)
  --tz TZ               IANA timezone; omit to use the agent's own timezone, pass one only to pin the schedule to that zone
  --in-minutes N        Fire in N minutes
  --in-hours N          Fire in N hours
  --in-days N           Fire in N days
  --recurring TYPE      hourly|daily|weekly|monthly|yearly
  --cron EXPR           Standard 5-field cron "min hour dom month dow"
  --fuzz-minutes N      Recurring/cron only: each fire lands within +/-N minutes of the nominal time

subcommands:
  create                Set a reminder
  list                  List active reminders (table shows the first 50; --json/--json-pretty list all unless --limit is given)
  get                   One reminder by id, deleted ones included (--field prints just that value)
  snooze                Reschedule a one-shot (works on fired ones too): --in-* from now, or --at <iso> [--tz <tz>]
  delete                Soft-delete a reminder: it never fires again and drops off list (see it with list --show-deleted)
  update                Rewrite a reminder in place, under the same id: --message, and --tz <zone>/--unpin-tz for a recurring schedule""")


def _serve_cmd(config: Config, argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="reminders serve")
    p.add_argument("--notifications-dir", default=str(Path.home() / "agent" / "notifications"))
    p.add_argument("--port", type=int, required=True, help="HTTP server port (allocated by vestad)")
    args = p.parse_args(argv)
    _run_serve(config, Path(args.notifications_dir), port=args.port)


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
        # SIGTERM is what `reminders daemon stop` sends, so it is the one exit the agent asked
        # for; every other way out of the loop below is news the agent needs.
        nonlocal shutdown_reason, asked_to_stop
        shutdown_reason = signal.Signals(signum).name
        asked_to_stop = signum == signal.SIGTERM
        raise SystemExit(0)

    # Installed before anything is brought up, so a signal arriving during startup is answered.
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    http_server = start_server(config, port)

    scheduler = create_scheduler()
    scheduler.start()
    commands.restore_all_jobs(config, scheduler, notif_dir=notif_dir)

    sync_interval = int(os.environ["REMINDERS_SYNC_INTERVAL"]) if "REMINDERS_SYNC_INTERVAL" in os.environ else 5

    print(json.dumps({"status": "serving", "sync_interval": sync_interval, "http_port": port}))
    sys.stdout.flush()
    try:
        while True:
            time.sleep(sync_interval)
            try:
                _sync_jobs(config, scheduler, notif_dir)
            except Exception:
                # A bad tick (locked db, malformed row) must not kill the daemon; retry next tick.
                logging.getLogger(__name__).exception("serve tick failed")
    finally:
        http_server.should_exit = True
        if not asked_to_stop:
            write_notification(notif_dir, "daemon_died", reason=shutdown_reason)
        scheduler.shutdown(wait=True)
