import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, UTC
from pathlib import Path

from .config import Config
from . import commands, db, monitor


def _write_pid(config):
    (config.data_dir / "serve.pid").write_text(str(os.getpid()))


def _remove_pid(config):
    try:
        (config.data_dir / "serve.pid").unlink()
    except FileNotFoundError:
        pass


def _write_death_notification(config, reason):
    config.notif_dir.mkdir(exist_ok=True)
    notif = {"timestamp": datetime.now(UTC).isoformat(), "source": "todo", "type": "daemon_died", "reason": reason}
    filename = f"{int(time.time() * 1e6)}-todo-daemon_died.json"
    (config.notif_dir / filename).write_text(json.dumps(notif))


def _require_daemon(config):
    pid_file = config.data_dir / "serve.pid"
    if not pid_file.exists():
        print(json.dumps({"error": "daemon not running — start with: todo serve &"}), file=sys.stderr)
        sys.exit(1)
    try:
        os.kill(int(pid_file.read_text().strip()), 0)
    except (ValueError, ProcessLookupError, OSError):
        pid_file.unlink(missing_ok=True)
        print(json.dumps({"error": "daemon not running (stale pid file) — start with: todo serve &"}), file=sys.stderr)
        sys.exit(1)


def build_config(args) -> Config:
    config = Config()
    if "state_dir" in vars(args) and args.state_dir:
        base = Path(args.state_dir)
        config.data_dir = base / "data" / "todo"
        config.log_dir = base / "logs" / "todo"
        config.notif_dir = base / "notifications"
    return config


def main():
    parser = argparse.ArgumentParser(prog="todo")
    parser.add_argument("--state-dir", type=str, help="Override state directory (default: ~)")
    sub = parser.add_subparsers(dest="command", required=True)

    # serve
    sub.add_parser("serve", help="Run background monitor daemon")

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

    # get
    p_get = sub.add_parser("get", help="Get a task by ID")
    p_get.add_argument("id_pos", nargs="?", default=None, metavar="id")
    p_get.add_argument("--id", default=None, dest="task_id")

    # update
    p_update = sub.add_parser("update", help="Update a task")
    p_update.add_argument("id_pos", nargs="?", default=None, metavar="id")
    p_update.add_argument("--id", default=None, dest="task_id")
    p_update.add_argument("--status", default=None)
    p_update.add_argument("--title", default=None)
    p_update.add_argument("--priority", default=None)

    # delete
    p_delete = sub.add_parser("delete", help="Delete a task")
    p_delete.add_argument("id_pos", nargs="?", default=None, metavar="id")
    p_delete.add_argument("--id", default=None, dest="task_id")

    # search
    p_search = sub.add_parser("search", help="Search tasks by title")
    p_search.add_argument("query_pos", nargs="?", default=None, metavar="query")
    p_search.add_argument("--query", default=None)
    p_search.add_argument("--show-completed", action="store_true")

    args = parser.parse_args()
    config = build_config(args)

    # Ensure dirs exist
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    config.notif_dir.mkdir(parents=True, exist_ok=True)

    # Init DB
    db.init_db(config.data_dir)

    try:
        if args.command == "serve":
            _run_serve(config)
            return

        _require_daemon(config)

        if args.command == "add":
            title = args.title_pos or args.title
            if not title:
                raise ValueError('title is required: todo add "title" or todo add --title "title"')
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
        elif args.command == "list":
            result = commands.list_tasks(config, show_completed=args.show_completed)
            print(json.dumps(result, indent=2))
        elif args.command == "get":
            task_id = args.id_pos or args.task_id
            if not task_id:
                raise ValueError("id is required: todo get <id> or todo get --id <id>")
            result = commands.get_task(config, task_id=task_id)
            print(json.dumps(result, indent=2))
        elif args.command == "update":
            task_id = args.id_pos or args.task_id
            if not task_id:
                raise ValueError("id is required: todo update <id> or todo update --id <id>")
            result = commands.update_task(
                config,
                task_id=task_id,
                status=args.status,
                title=args.title,
                priority=args.priority,
            )
            print(json.dumps(result, indent=2))
        elif args.command == "delete":
            task_id = args.id_pos or args.task_id
            if not task_id:
                raise ValueError("id is required: todo delete <id> or todo delete --id <id>")
            result = commands.delete_task(config, task_id=task_id)
            print(json.dumps(result, indent=2))
        elif args.command == "search":
            query = args.query_pos or args.query
            if not query:
                raise ValueError('query is required: todo search "query" or todo search --query "query"')
            result = commands.search_tasks(config, query=query, show_completed=args.show_completed)
            print(json.dumps(result, indent=2))
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


def _run_serve(config: Config):
    logger = logging.getLogger("todo-monitor")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(config.log_dir / "monitor.log")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)
    # Also log to stderr for visibility
    logger.addHandler(logging.StreamHandler())

    stop_event = threading.Event()
    shutdown_reason = "unknown"

    def handle_signal(signum, frame):
        nonlocal shutdown_reason
        shutdown_reason = signal.Signals(signum).name
        stop_event.set()

    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print(json.dumps({"status": "serving", "monitor_interval": config.monitor_interval}))
    sys.stdout.flush()

    _write_pid(config)
    try:
        monitor.run(
            config.data_dir / "tasks.db",
            config.notif_dir,
            stop_event,
            logger,
            config.monitor_interval,
        )
    finally:
        _write_death_notification(config, shutdown_reason)
        _remove_pid(config)
