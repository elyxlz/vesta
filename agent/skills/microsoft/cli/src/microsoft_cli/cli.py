import argparse
import json
import logging
import os
import signal
import sys
import threading

import httpx

from .config import Config
from . import auth_commands, email, calendar, monitor, notifications
from .context import MicrosoftContext
from .settings import MicrosoftSettings


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
        print(json.dumps({"error": "daemon not running — start with: screen -dmS microsoft microsoft serve"}), file=sys.stderr)
        sys.exit(1)
    try:
        os.kill(int(pid_file.read_text().strip()), 0)
    except (ValueError, ProcessLookupError, OSError):
        pid_file.unlink(missing_ok=True)
        print(json.dumps({"error": "daemon not running (stale pid file) — start with: screen -dmS microsoft microsoft serve"}), file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(prog="microsoft")
    group = parser.add_subparsers(dest="group", required=True)

    # serve
    group.add_parser("serve")

    # auth
    auth_parser = group.add_parser("auth")
    auth_sub = auth_parser.add_subparsers(dest="command", required=True)
    auth_sub.add_parser("login")
    p_complete = auth_sub.add_parser("complete")
    p_complete.add_argument("--flow-cache", required=True)
    auth_sub.add_parser("list")

    # email
    email_parser = group.add_parser("email")
    email_sub = email_parser.add_subparsers(dest="command", required=True)

    p_list_emails = email_sub.add_parser("list")
    p_list_emails.add_argument("--account", required=True)
    p_list_emails.add_argument("--folder", default="inbox")
    p_list_emails.add_argument("--limit", type=int, default=10)

    p_get_email = email_sub.add_parser("get")
    p_get_email.add_argument("--account", required=True)
    p_get_email.add_argument("--id", required=True, dest="email_id")
    p_get_email.add_argument("--no-attachments", action="store_true")
    p_get_email.add_argument("--save-to", default=None)

    p_send = email_sub.add_parser("send")
    p_send.add_argument("--account", required=True)
    p_send.add_argument("--to", nargs="+", default=None)
    p_send.add_argument("--subject", required=True)
    p_send.add_argument("--body", required=True)
    p_send.add_argument("--cc", nargs="+", default=None)
    p_send.add_argument("--bcc", nargs="+", default=None)
    p_send.add_argument("--attachments", nargs="+", default=None)
    p_send.add_argument("--html", action="store_true", default=False)

    p_draft = email_sub.add_parser("draft")
    p_draft.add_argument("--account", required=True)
    p_draft.add_argument("--to", nargs="+", default=None)
    p_draft.add_argument("--subject", required=True)
    p_draft.add_argument("--body", required=True)
    p_draft.add_argument("--cc", nargs="+", default=None)
    p_draft.add_argument("--bcc", nargs="+", default=None)
    p_draft.add_argument("--attachments", nargs="+", default=None)

    p_reply = email_sub.add_parser("reply")
    p_reply.add_argument("--account", required=True)
    p_reply.add_argument("--id", required=True, dest="email_id")
    p_reply.add_argument("--body", required=True)
    p_reply.add_argument("--attachments", nargs="+", default=None)
    p_reply.add_argument("--reply-all", action="store_true")

    p_attachment = email_sub.add_parser("attachment")
    p_attachment.add_argument("--account", required=True)
    p_attachment.add_argument("--email-id", required=True)
    p_attachment.add_argument("--attachment-id", required=True)
    p_attachment.add_argument("--save-path", required=True)

    p_search = email_sub.add_parser("search")
    p_search.add_argument("--account", required=True)
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--folder", default=None)

    p_update = email_sub.add_parser("update")
    p_update.add_argument("--account", required=True)
    p_update.add_argument("--id", required=True, dest="email_id")
    p_update.add_argument("--is-read", type=lambda x: x.lower() == "true", default=None)
    p_update.add_argument("--categories", nargs="+", default=None)

    # calendar
    cal_parser = group.add_parser("calendar")
    cal_sub = cal_parser.add_subparsers(dest="command", required=True)

    p_list_events = cal_sub.add_parser("list")
    p_list_events.add_argument("--account", required=True)
    p_list_events.add_argument("--calendar-name", default=None)
    p_list_events.add_argument("--days-ahead", type=int, default=7)
    p_list_events.add_argument("--days-back", type=int, default=0)
    p_list_events.add_argument("--no-details", action="store_true")
    p_list_events.add_argument("--user-timezone", default=None)

    p_list_cals = cal_sub.add_parser("calendars")
    p_list_cals.add_argument("--account", required=True)

    p_get_event = cal_sub.add_parser("get")
    p_get_event.add_argument("--account", required=True)
    p_get_event.add_argument("--id", required=True, dest="event_id")

    p_create_event = cal_sub.add_parser("create")
    p_create_event.add_argument("--account", required=True)
    p_create_event.add_argument("--subject", required=True)
    p_create_event.add_argument("--start", required=True)
    p_create_event.add_argument("--end", default=None)
    p_create_event.add_argument("--location", default=None)
    p_create_event.add_argument("--body", default=None)
    p_create_event.add_argument("--attendees", nargs="+", default=None)
    p_create_event.add_argument("--timezone", required=True)
    p_create_event.add_argument("--calendar-name", default=None)
    p_create_event.add_argument("--all-day", action="store_true")
    p_create_event.add_argument("--recurrence", choices=["daily", "weekly", "monthly", "yearly"], default=None)
    p_create_event.add_argument("--recurrence-end-date", default=None)

    p_update_event = cal_sub.add_parser("update")
    p_update_event.add_argument("--account", required=True)
    p_update_event.add_argument("--id", required=True, dest="event_id")
    p_update_event.add_argument("--subject", default=None)
    p_update_event.add_argument("--start", default=None)
    p_update_event.add_argument("--end", default=None)
    p_update_event.add_argument("--location", default=None)
    p_update_event.add_argument("--body", default=None)
    p_update_event.add_argument("--timezone", default=None)

    p_delete_event = cal_sub.add_parser("delete")
    p_delete_event.add_argument("--account", required=True)
    p_delete_event.add_argument("--id", required=True, dest="event_id")
    p_delete_event.add_argument("--no-cancellation", action="store_true")

    p_respond = cal_sub.add_parser("respond")
    p_respond.add_argument("--account", required=True)
    p_respond.add_argument("--id", required=True, dest="event_id")
    p_respond.add_argument("--response", choices=["accept", "decline", "tentativelyAccept"], default="accept")
    p_respond.add_argument("--message", default=None)

    args = parser.parse_args()
    config = Config()

    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    config.notif_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.group == "serve":
            _run_serve(config)
            return

        if args.group != "auth":
            _require_daemon(config)

        if args.group == "auth":
            result = _dispatch_auth(args, config)
            print(json.dumps(result, indent=2))
        elif args.group in ("email", "calendar"):
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                if args.group == "email":
                    result = _dispatch_email(args, config, client)
                else:
                    result = _dispatch_calendar(args, config, client)
                print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


def _dispatch_auth(args, config):
    if args.command == "list":
        return auth_commands.list_accounts(config)
    elif args.command == "login":
        return auth_commands.authenticate_account(config)
    elif args.command == "complete":
        return auth_commands.complete_authentication(config, flow_cache=args.flow_cache)


def _dispatch_email(args, config, client):
    if args.command == "list":
        return email.list_emails(config, client, account_email=args.account, folder=args.folder, limit=args.limit)
    elif args.command == "get":
        return email.get_email(
            config,
            client,
            account_email=args.account,
            email_id=args.email_id,
            include_attachments=not args.no_attachments,
            save_to_file=args.save_to,
        )
    elif args.command == "send":
        return email.send_email(
            config,
            client,
            account_email=args.account,
            to=args.to,
            subject=args.subject,
            body=args.body,
            cc=args.cc,
            bcc=args.bcc,
            attachments=args.attachments,
            html=args.html,
        )
    elif args.command == "draft":
        return email.create_email_draft(
            config,
            client,
            account_email=args.account,
            to=args.to,
            subject=args.subject,
            body=args.body,
            cc=args.cc,
            bcc=args.bcc,
            attachments=args.attachments,
        )
    elif args.command == "reply":
        return email.reply_to_email(
            config,
            client,
            account_email=args.account,
            email_id=args.email_id,
            body=args.body,
            attachments=args.attachments,
            reply_all=args.reply_all,
        )
    elif args.command == "attachment":
        return email.get_attachment(
            config, client, account_email=args.account, email_id=args.email_id, attachment_id=args.attachment_id, save_path=args.save_path
        )
    elif args.command == "search":
        return email.search_emails(config, client, account_email=args.account, query=args.query, limit=args.limit, folder=args.folder)
    elif args.command == "update":
        return email.update_email(
            config, client, account_email=args.account, email_id=args.email_id, is_read=args.is_read, categories=args.categories
        )


def _dispatch_calendar(args, config, client):
    if args.command == "list":
        return calendar.list_events(
            config,
            client,
            account_email=args.account,
            calendar_name=args.calendar_name,
            days_ahead=args.days_ahead,
            days_back=args.days_back,
            include_details=not args.no_details,
            user_timezone=args.user_timezone,
        )
    elif args.command == "calendars":
        return calendar.list_calendars(config, client, account_email=args.account)
    elif args.command == "get":
        return calendar.get_event(config, client, account_email=args.account, event_id=args.event_id)
    elif args.command == "create":
        return calendar.create_event(
            config,
            client,
            account_email=args.account,
            subject=args.subject,
            start=args.start,
            end=args.end,
            location=args.location,
            body=args.body,
            attendees=args.attendees,
            timezone=args.timezone,
            calendar_name=args.calendar_name,
            is_all_day=args.all_day,
            recurrence=args.recurrence,
            recurrence_end_date=args.recurrence_end_date,
        )
    elif args.command == "update":
        return calendar.update_event(
            config,
            client,
            account_email=args.account,
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
            config, client, account_email=args.account, event_id=args.event_id, send_cancellation=not args.no_cancellation
        )
    elif args.command == "respond":
        return calendar.respond_event(
            config, client, account_email=args.account, event_id=args.event_id, response=args.response, message=args.message
        )


def _run_serve(config: Config):
    settings = MicrosoftSettings()
    http_client = httpx.Client(timeout=30.0, follow_redirects=True)

    monitor_base_dir = config.data_dir / "monitor"
    monitor_base_dir.mkdir(parents=True, exist_ok=True)
    monitor_state_file = monitor_base_dir / "state.txt"
    monitor_log_file = config.log_dir / "monitor.log"

    monitor_logger = logging.getLogger("microsoft.monitor")
    monitor_logger.setLevel(logging.INFO)
    if not monitor_logger.handlers:
        file_handler = logging.FileHandler(monitor_log_file)
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        monitor_logger.addHandler(file_handler)
        monitor_logger.addHandler(logging.StreamHandler())

    monitor_stop_event = threading.Event()

    ctx = MicrosoftContext(
        cache_file=config.cache_file,
        http_client=http_client,
        log_dir=config.log_dir,
        notif_dir=config.notif_dir,
        monitor_base_dir=monitor_base_dir,
        monitor_state_file=monitor_state_file,
        monitor_log_file=monitor_log_file,
        monitor_logger=monitor_logger,
        monitor_stop_event=monitor_stop_event,
        scopes=config.scopes,
        base_url=config.base_url,
        upload_chunk_size=config.upload_chunk_size,
        folders=config.folders,
        settings=settings,
        calendar_notify_thresholds=config.calendar_notify_thresholds,
    )

    shutdown_reason = "unknown"

    def handle_signal(signum, frame):
        nonlocal shutdown_reason
        shutdown_reason = signal.Signals(signum).name
        monitor_stop_event.set()

    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print(json.dumps({"status": "serving"}))
    sys.stdout.flush()

    _write_pid(config)
    try:
        monitor.run(ctx)
    finally:
        notifications.write_notification(config.notif_dir, "daemon_died", reason=shutdown_reason)
        _remove_pid(config)
        http_client.close()
