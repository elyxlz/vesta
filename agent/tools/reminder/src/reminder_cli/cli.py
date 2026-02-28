import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, UTC
from pathlib import Path

from .config import Config
from . import commands, db
from .scheduler import create_scheduler


def _write_pid(config):
    (config.data_dir / "serve.pid").write_text(str(os.getpid()))


def _remove_pid(config):
    try:
        (config.data_dir / "serve.pid").unlink()
    except FileNotFoundError:
        pass


def _write_death_notification(config, reason):
    config.notif_dir.mkdir(exist_ok=True)
    notif = {"timestamp": datetime.now(UTC).isoformat(), "source": "reminder", "type": "daemon_died", "reason": reason}
    filename = f"{int(time.time() * 1e6)}-reminder-daemon_died.json"
    tmp = config.notif_dir / f"{filename}.tmp"
    tmp.write_text(json.dumps(notif))
    os.replace(tmp, config.notif_dir / filename)


def _require_daemon(config):
    pid_file = config.data_dir / "serve.pid"
    if not pid_file.exists():
        print(json.dumps({"error": "daemon not running — start with: reminder serve &"}), file=sys.stderr)
        sys.exit(1)
    try:
        os.kill(int(pid_file.read_text().strip()), 0)
    except (ValueError, ProcessLookupError, OSError):
        pid_file.unlink(missing_ok=True)
        print(json.dumps({"error": "daemon not running (stale pid file) — start with: reminder serve &"}), file=sys.stderr)
        sys.exit(1)


def build_config(args) -> Config:
    config = Config()
    if "state_dir" in vars(args) and args.state_dir:
        base = Path(args.state_dir)
        config.data_dir = base / "data" / "reminder"
        config.log_dir = base / "logs" / "reminder"
        config.notif_dir = base / "notifications"
    return config


def _init_scheduler(config: Config):
    scheduler = create_scheduler(config.data_dir)
    scheduler.start()
    db.init_db(config.data_dir)
    commands.restore_all_jobs(config, scheduler)
    return scheduler


def main():
    parser = argparse.ArgumentParser(prog="reminder")
    parser.add_argument("--state-dir", type=str, help="Override state directory (default: ~)")
    sub = parser.add_subparsers(dest="command", required=True)

    # serve
    sub.add_parser("serve", help="Run scheduler daemon")

    # set
    p_set = sub.add_parser("set", help="Set a reminder")
    p_set.add_argument("message_pos", nargs="?", default=None, metavar="message")
    p_set.add_argument("--message", default=None)
    p_set.add_argument("--scheduled-datetime", default=None)
    p_set.add_argument("--tz", default=None)
    p_set.add_argument("--in-minutes", type=int, default=None)
    p_set.add_argument("--in-hours", type=int, default=None)
    p_set.add_argument("--in-days", type=int, default=None)
    p_set.add_argument("--recurring", default=None, choices=["hourly", "daily", "weekly", "monthly", "yearly"])

    # list
    p_list = sub.add_parser("list", help="List active reminders")
    p_list.add_argument("--limit", type=int, default=50)

    # update
    p_update = sub.add_parser("update", help="Update a reminder message")
    p_update.add_argument("id_pos", nargs="?", default=None, metavar="id")
    p_update.add_argument("--id", default=None, dest="reminder_id")
    p_update.add_argument("--message", required=True)

    # cancel
    p_cancel = sub.add_parser("cancel", help="Cancel a reminder")
    p_cancel.add_argument("id_pos", nargs="?", default=None, metavar="id")
    p_cancel.add_argument("--id", default=None, dest="reminder_id")

    args = parser.parse_args()
    config = build_config(args)

    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    config.notif_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.command == "serve":
            _run_serve(config)
            return

        _require_daemon(config)

        scheduler = _init_scheduler(config)
        try:
            result = _dispatch(args, config, scheduler)
            print(json.dumps(result, indent=2))
        finally:
            scheduler.shutdown(wait=False)
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


def _dispatch(args, config: Config, scheduler):
    if args.command == "set":
        message = args.message_pos or args.message
        if not message:
            raise ValueError('message is required: reminder set "message" or reminder set --message "message"')
        return commands.set_reminder(
            config,
            scheduler,
            message=message,
            scheduled_datetime=args.scheduled_datetime,
            tz=args.tz,
            in_minutes=args.in_minutes,
            in_hours=args.in_hours,
            in_days=args.in_days,
            recurring=args.recurring,
        )
    elif args.command == "list":
        return commands.list_reminders(config, scheduler, limit=args.limit)
    elif args.command == "update":
        reminder_id = args.id_pos or args.reminder_id
        if not reminder_id:
            raise ValueError("id is required: reminder update <id> or reminder update --id <id>")
        return commands.update_reminder(config, scheduler, reminder_id=reminder_id, message=args.message)
    elif args.command == "cancel":
        reminder_id = args.id_pos or args.reminder_id
        if not reminder_id:
            raise ValueError("id is required: reminder cancel <id> or reminder cancel --id <id>")
        return commands.cancel_reminder(config, scheduler, reminder_id=reminder_id)


def _sync_jobs(config: Config, scheduler):
    scheduled_ids = {job.id for job in scheduler.get_jobs()}
    from contextlib import closing

    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT id FROM reminders WHERE completed = 0 AND trigger_data IS NOT NULL")
        db_ids = {row["id"] for row in cursor}

    stale_ids = scheduled_ids - db_ids
    for sid in stale_ids:
        try:
            scheduler.remove_job(sid)
        except Exception:
            pass

    new_ids = db_ids - scheduled_ids
    if new_ids:
        commands.restore_all_jobs(config, scheduler)


def _run_serve(config: Config):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(config.log_dir / "reminder.log"),
            logging.StreamHandler(),
        ],
    )

    scheduler = _init_scheduler(config)
    stop = False
    shutdown_reason = "unknown"

    def handle_signal(signum, frame):
        nonlocal stop, shutdown_reason
        shutdown_reason = signal.Signals(signum).name
        stop = True

    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print(json.dumps({"status": "serving"}))
    sys.stdout.flush()

    sync_interval = int(os.environ.get("REMINDER_SYNC_INTERVAL", "5"))

    _write_pid(config)
    try:
        while not stop:
            time.sleep(sync_interval)
            _sync_jobs(config, scheduler)
    finally:
        _write_death_notification(config, shutdown_reason)
        _remove_pid(config)
        scheduler.shutdown(wait=True)
