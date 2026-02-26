import argparse
import json
import logging
import os
import signal
import sys
import threading
from pathlib import Path

from .config import Config
from . import auth_commands, gmail, calendar, meet, monitor
from .context import GoogleContext


def _write_pid(config):
    (config.data_dir / "serve.pid").write_text(str(os.getpid()))


def _remove_pid(config):
    try:
        (config.data_dir / "serve.pid").unlink()
    except FileNotFoundError:
        pass


def _require_daemon(config):
    pid_file = config.data_dir / "serve.pid"
    if not pid_file.exists():
        print(json.dumps({"error": "daemon not running — start with: google serve &"}), file=sys.stderr)
        sys.exit(1)
    try:
        os.kill(int(pid_file.read_text().strip()), 0)
    except (ValueError, ProcessLookupError, OSError):
        pid_file.unlink(missing_ok=True)
        print(json.dumps({"error": "daemon not running (stale pid file) — start with: google serve &"}), file=sys.stderr)
        sys.exit(1)


def build_config(args) -> Config:
    config = Config()
    if "state_dir" in vars(args) and args.state_dir:
        base = Path(args.state_dir)
        config.data_dir = base / "data" / "google"
        config.log_dir = base / "logs" / "google"
        config.notif_dir = base / "notifications"
    return config


def main():
    parser = argparse.ArgumentParser(prog="google")
    parser.add_argument("--state-dir", type=str)
    group = parser.add_subparsers(dest="group", required=True)

    # serve
    group.add_parser("serve")

    # auth
    auth_parser = group.add_parser("auth")
    auth_sub = auth_parser.add_subparsers(dest="command", required=True)
    auth_sub.add_parser("login")
    auth_sub.add_parser("login-local")
    p_complete = auth_sub.add_parser("complete")
    p_complete.add_argument("--code", required=True)
    auth_sub.add_parser("list")

    # email
    email_parser = group.add_parser("email")
    email_sub = email_parser.add_subparsers(dest="command", required=True)

    p_list_emails = email_sub.add_parser("list")
    p_list_emails.add_argument("--label", default="INBOX")
    p_list_emails.add_argument("--limit", type=int, default=10)

    p_get_email = email_sub.add_parser("get")
    p_get_email.add_argument("--id", required=True, dest="message_id")
    p_get_email.add_argument("--no-attachments", action="store_true")
    p_get_email.add_argument("--save-to", default=None)

    p_send = email_sub.add_parser("send")
    p_send.add_argument("--to", required=True, nargs="+")
    p_send.add_argument("--subject", required=True)
    p_send.add_argument("--body", required=True)
    p_send.add_argument("--cc", nargs="+", default=None)
    p_send.add_argument("--attachments", nargs="+", default=None)

    p_draft = email_sub.add_parser("draft")
    p_draft.add_argument("--to", required=True, nargs="+")
    p_draft.add_argument("--subject", required=True)
    p_draft.add_argument("--body", required=True)
    p_draft.add_argument("--cc", nargs="+", default=None)
    p_draft.add_argument("--attachments", nargs="+", default=None)

    p_reply = email_sub.add_parser("reply")
    p_reply.add_argument("--id", required=True, dest="message_id")
    p_reply.add_argument("--body", required=True)
    p_reply.add_argument("--attachments", nargs="+", default=None)
    p_reply.add_argument("--reply-all", action="store_true")

    p_attachment = email_sub.add_parser("attachment")
    p_attachment.add_argument("--email-id", required=True)
    p_attachment.add_argument("--attachment-id", required=True)
    p_attachment.add_argument("--save-path", required=True)

    p_search = email_sub.add_parser("search")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--label", default=None)

    p_update = email_sub.add_parser("update")
    p_update.add_argument("--id", required=True, dest="message_id")
    p_update.add_argument("--add-labels", nargs="+", default=None)
    p_update.add_argument("--remove-labels", nargs="+", default=None)

    # calendar
    cal_parser = group.add_parser("calendar")
    cal_sub = cal_parser.add_subparsers(dest="command", required=True)

    p_list_events = cal_sub.add_parser("list")
    p_list_events.add_argument("--calendar", default="primary")
    p_list_events.add_argument("--days-ahead", type=int, default=7)
    p_list_events.add_argument("--days-back", type=int, default=0)
    p_list_events.add_argument("--no-details", action="store_true")
    p_list_events.add_argument("--user-timezone", default=None)

    p_list_cals = cal_sub.add_parser("calendars")

    p_get_event = cal_sub.add_parser("get")
    p_get_event.add_argument("--id", required=True, dest="event_id")
    p_get_event.add_argument("--calendar", default="primary")

    p_create_event = cal_sub.add_parser("create")
    p_create_event.add_argument("--subject", required=True)
    p_create_event.add_argument("--start", required=True)
    p_create_event.add_argument("--end", default=None)
    p_create_event.add_argument("--location", default=None)
    p_create_event.add_argument("--body", default=None)
    p_create_event.add_argument("--attendees", nargs="+", default=None)
    p_create_event.add_argument("--timezone", required=True)
    p_create_event.add_argument("--calendar", default="primary")
    p_create_event.add_argument("--all-day", action="store_true")
    p_create_event.add_argument("--recurrence", choices=["daily", "weekly", "monthly", "yearly"], default=None)
    p_create_event.add_argument("--recurrence-end-date", default=None)
    p_create_event.add_argument("--meet-link", action="store_true")

    p_update_event = cal_sub.add_parser("update")
    p_update_event.add_argument("--id", required=True, dest="event_id")
    p_update_event.add_argument("--calendar", default="primary")
    p_update_event.add_argument("--subject", default=None)
    p_update_event.add_argument("--start", default=None)
    p_update_event.add_argument("--end", default=None)
    p_update_event.add_argument("--location", default=None)
    p_update_event.add_argument("--body", default=None)
    p_update_event.add_argument("--timezone", default=None)

    p_delete_event = cal_sub.add_parser("delete")
    p_delete_event.add_argument("--id", required=True, dest="event_id")
    p_delete_event.add_argument("--calendar", default="primary")
    p_delete_event.add_argument("--no-notification", action="store_true")

    p_respond = cal_sub.add_parser("respond")
    p_respond.add_argument("--id", required=True, dest="event_id")
    p_respond.add_argument("--calendar", default="primary")
    p_respond.add_argument("--response", choices=["accept", "decline", "tentative"], default="accept")
    p_respond.add_argument("--message", default=None)

    # meet
    meet_parser = group.add_parser("meet")
    meet_sub = meet_parser.add_subparsers(dest="command", required=True)
    meet_sub.add_parser("create")

    args = parser.parse_args()
    config = build_config(args)

    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    config.notif_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.group == "serve":
            _run_serve(config)
            return

        if args.group not in ("auth", "meet"):
            _require_daemon(config)

        if args.group == "auth":
            result = _dispatch_auth(args, config)
            print(json.dumps(result, indent=2))
        elif args.group == "email":
            result = _dispatch_email(args, config)
            print(json.dumps(result, indent=2))
        elif args.group == "calendar":
            result = _dispatch_calendar(args, config)
            print(json.dumps(result, indent=2))
        elif args.group == "meet":
            result = _dispatch_meet(args, config)
            print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


def _dispatch_auth(args, config):
    if args.command == "list":
        return auth_commands.list_accounts(config)
    elif args.command == "login":
        return auth_commands.authenticate_account(config)
    elif args.command == "login-local":
        return auth_commands.run_local_auth(config)
    elif args.command == "complete":
        return auth_commands.complete_authentication(config, code=args.code)


def _dispatch_email(args, config):
    if args.command == "list":
        return gmail.list_emails(config, label=args.label, limit=args.limit)
    elif args.command == "get":
        return gmail.get_email(config, message_id=args.message_id, include_attachments=not args.no_attachments, save_to_file=args.save_to)
    elif args.command == "send":
        return gmail.send_email(config, to=args.to, subject=args.subject, body=args.body, cc=args.cc, attachments=args.attachments)
    elif args.command == "draft":
        return gmail.create_draft(config, to=args.to, subject=args.subject, body=args.body, cc=args.cc, attachments=args.attachments)
    elif args.command == "reply":
        return gmail.reply_to_email(config, message_id=args.message_id, body=args.body, attachments=args.attachments, reply_all=args.reply_all)
    elif args.command == "attachment":
        return gmail.get_attachment(config, email_id=args.email_id, attachment_id=args.attachment_id, save_path=args.save_path)
    elif args.command == "search":
        return gmail.search_emails(config, query=args.query, limit=args.limit, label=args.label)
    elif args.command == "update":
        return gmail.update_email(config, message_id=args.message_id, add_labels=args.add_labels, remove_labels=args.remove_labels)


def _dispatch_calendar(args, config):
    if args.command == "list":
        return calendar.list_events(
            config,
            calendar_id=args.calendar,
            days_ahead=args.days_ahead,
            days_back=args.days_back,
            include_details=not args.no_details,
            user_timezone=args.user_timezone,
        )
    elif args.command == "calendars":
        return calendar.list_calendars(config)
    elif args.command == "get":
        return calendar.get_event(config, calendar_id=args.calendar, event_id=args.event_id)
    elif args.command == "create":
        return calendar.create_event(
            config,
            calendar_id=args.calendar,
            subject=args.subject,
            start=args.start,
            end=args.end,
            location=args.location,
            body=args.body,
            attendees=args.attendees,
            timezone=args.timezone,
            all_day=args.all_day,
            recurrence=args.recurrence,
            recurrence_end_date=args.recurrence_end_date,
            meet_link=args.meet_link,
        )
    elif args.command == "update":
        return calendar.update_event(
            config,
            calendar_id=args.calendar,
            event_id=args.event_id,
            subject=args.subject,
            start=args.start,
            end=args.end,
            location=args.location,
            body=args.body,
            timezone=args.timezone,
        )
    elif args.command == "delete":
        return calendar.delete_event(
            config,
            calendar_id=args.calendar,
            event_id=args.event_id,
            send_updates="none" if args.no_notification else "all",
        )
    elif args.command == "respond":
        return calendar.respond_event(
            config,
            calendar_id=args.calendar,
            event_id=args.event_id,
            response=args.response,
            message=args.message,
        )


def _dispatch_meet(args, config):
    if args.command == "create":
        return meet.create_space(config)


def _run_serve(config: Config):
    monitor_base_dir = config.data_dir / "monitor"
    monitor_base_dir.mkdir(parents=True, exist_ok=True)
    monitor_state_file = monitor_base_dir / "state.txt"
    monitor_log_file = config.log_dir / "monitor.log"

    monitor_logger = logging.getLogger("google.monitor")
    monitor_logger.setLevel(logging.INFO)
    if not monitor_logger.handlers:
        file_handler = logging.FileHandler(monitor_log_file)
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        monitor_logger.addHandler(file_handler)
        monitor_logger.addHandler(logging.StreamHandler())

    monitor_stop_event = threading.Event()

    ctx = GoogleContext(
        config=config,
        monitor_base_dir=monitor_base_dir,
        monitor_state_file=monitor_state_file,
        monitor_log_file=monitor_log_file,
        monitor_logger=monitor_logger,
        monitor_stop_event=monitor_stop_event,
    )

    def handle_signal(signum, frame):
        monitor_stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print(json.dumps({"status": "serving"}))
    sys.stdout.flush()

    _write_pid(config)
    try:
        monitor.run(ctx)
    finally:
        _remove_pid(config)
