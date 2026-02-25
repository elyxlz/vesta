import argparse
import json
import logging
import signal
import sys
import threading
from pathlib import Path

from .config import Config
from . import commands, db, monitor


def build_config(args) -> Config:
    config = Config()
    if "state_dir" in vars(args) and args.state_dir:
        base = Path(args.state_dir)
        config.data_dir = base / "data" / "task"
        config.log_dir = base / "logs" / "task"
        config.notif_dir = base / "notifications"
    return config


def main():
    parser = argparse.ArgumentParser(prog="task")
    parser.add_argument("--state-dir", type=str, help="Override state directory (default: ~)")
    sub = parser.add_subparsers(dest="command", required=True)

    # serve
    sub.add_parser("serve", help="Run background monitor daemon")

    # add
    p_add = sub.add_parser("add", help="Add a new task")
    p_add.add_argument("--title", required=True)
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
    p_get.add_argument("--id", required=True, dest="task_id")

    # update
    p_update = sub.add_parser("update", help="Update a task")
    p_update.add_argument("--id", required=True, dest="task_id")
    p_update.add_argument("--status", default=None)
    p_update.add_argument("--title", default=None)
    p_update.add_argument("--priority", default=None)

    # delete
    p_delete = sub.add_parser("delete", help="Delete a task")
    p_delete.add_argument("--id", required=True, dest="task_id")

    # search
    p_search = sub.add_parser("search", help="Search tasks by title")
    p_search.add_argument("--query", required=True)
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
        elif args.command == "add":
            result = commands.add_task(
                config,
                title=args.title,
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
            result = commands.get_task(config, task_id=args.task_id)
            print(json.dumps(result, indent=2))
        elif args.command == "update":
            result = commands.update_task(
                config,
                task_id=args.task_id,
                status=args.status,
                title=args.title,
                priority=args.priority,
            )
            print(json.dumps(result, indent=2))
        elif args.command == "delete":
            result = commands.delete_task(config, task_id=args.task_id)
            print(json.dumps(result, indent=2))
        elif args.command == "search":
            result = commands.search_tasks(config, query=args.query, show_completed=args.show_completed)
            print(json.dumps(result, indent=2))
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


def _run_serve(config: Config):
    logger = logging.getLogger("task-monitor")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(config.log_dir / "monitor.log")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)
    # Also log to stderr for visibility
    logger.addHandler(logging.StreamHandler())

    stop_event = threading.Event()

    def handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print(json.dumps({"status": "serving", "monitor_interval": config.monitor_interval}))
    sys.stdout.flush()

    monitor.run(
        config.data_dir / "tasks.db",
        config.notif_dir,
        stop_event,
        logger,
        config.monitor_interval,
    )
