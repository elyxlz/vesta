import argparse
import json
import logging
import os
import signal
import sys
import threading
from pathlib import Path

import httpx

from .config import Config
from . import auth_commands, email, calendar, monitor, notifications, block, format as fmt
from . import backend, owa_commands, owa_rest, owa_rest_commands
from .context import MicrosoftContext
from .settings import MicrosoftSettings


def _write_pid(config):
    (config.data_dir / "serve.pid").write_text(str(os.getpid()))


def _remove_pid(config):
    try:
        (config.data_dir / "serve.pid").unlink()
    except FileNotFoundError:
        pass


def _add_format_flags(parser: argparse.ArgumentParser) -> None:
    """Attach mutually-exclusive --json / --json-pretty flags to a list-style subparser."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true", help="Emit compact JSON instead of a table.")
    group.add_argument("--json-pretty", action="store_true", help="Emit indented JSON instead of a table.")


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
    p_serve = group.add_parser("serve")
    p_serve.add_argument("--notifications-dir", required=True)

    # auth
    auth_parser = group.add_parser("auth")
    auth_sub = auth_parser.add_subparsers(dest="command", required=True)
    auth_sub.add_parser("login")
    p_complete = auth_sub.add_parser("complete")
    p_complete.add_argument("--flow-cache", required=True)
    auth_sub.add_parser("list")
    p_owa_login = auth_sub.add_parser(
        "owa-login", help="Capture OWA REST token from a signed-in browser session (one-step setup for locked tenants)."
    )
    p_owa_login.add_argument("--account", required=True, help="Email address to capture the token for.")

    # email
    email_parser = group.add_parser("email")
    email_sub = email_parser.add_subparsers(dest="command", required=True)

    p_list_emails = email_sub.add_parser("list")
    p_list_emails.add_argument("--account", required=True)
    p_list_emails.add_argument("--folder", default="inbox")
    p_list_emails.add_argument("--limit", type=int, default=10)
    _add_format_flags(p_list_emails)

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
    p_reply.add_argument("--html", action="store_true")

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
    _add_format_flags(p_search)

    p_update = email_sub.add_parser("update")
    p_update.add_argument("--account", required=True)
    p_update.add_argument("--id", required=True, dest="email_id")
    p_update.add_argument("--is-read", type=lambda x: x.lower() == "true", default=None)
    p_update.add_argument("--categories", nargs="+", default=None)

    p_delete = email_sub.add_parser("delete")
    p_delete.add_argument("--account", required=True)
    p_delete_group = p_delete.add_mutually_exclusive_group(required=True)
    p_delete_group.add_argument("--id", default=None, dest="email_id", help="ID of a single message to delete")
    p_delete_group.add_argument("--sender", default=None, help="Delete all messages from this sender address")
    p_delete.add_argument("--permanent", action="store_true", help="Hard delete instead of moving to Deleted Items")

    p_block = email_sub.add_parser("block")
    p_block.add_argument("--account", required=True)
    p_block_group = p_block.add_mutually_exclusive_group(required=True)
    p_block_group.add_argument("--sender", default=None, help="Email address of sender to block")
    p_block_group.add_argument("--list", action="store_true", default=False, help="List all current block rules")

    p_unblock = email_sub.add_parser("unblock")
    p_unblock.add_argument("--account", required=True)
    p_unblock.add_argument("--sender", required=True, help="Email address of sender to unblock")

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
    _add_format_flags(p_list_events)

    p_list_cals = cal_sub.add_parser("calendars")
    p_list_cals.add_argument("--account", required=True)
    _add_format_flags(p_list_cals)

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

    # Backend selector on every email/calendar subcommand.
    # auto  - Graph first; on permission failure: EWS (if device-flow token cached)
    #         or REST (if browser-captured token available).
    # graph - force the official Graph API.
    # owa   - force the reverse-engineered EWS path.
    # owa-rest - force the OWA REST path (requires: microsoft auth owa-login).
    for sub in (email_sub, cal_sub):
        for sp in sub.choices.values():
            sp.add_argument(
                "--backend",
                choices=[backend.AUTO, backend.GRAPH, backend.OWA, backend.OWA_REST],
                default=backend.AUTO,
                help=("Path: auto (Graph then OWA fallback), graph, owa (EWS), or owa-rest (browser-captured token; requires auth owa-login)."),
            )

    args = parser.parse_args()
    config = Config()

    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.group == "serve":
            _run_serve(config, Path(args.notifications_dir))
            return

        if args.group != "auth":
            _require_daemon(config)

        if args.group == "auth":
            result = _dispatch_auth(args, config)
            print(json.dumps(fmt.strip_odata(result), indent=2))
        elif args.group in ("email", "calendar"):
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                if args.group == "email":
                    result = _dispatch_email(args, config, client)
                else:
                    result = _dispatch_calendar(args, config, client)
                _print_result(args, result)
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


_COMPACT_FORMATTERS = {
    ("email", "list"): fmt.format_email_list,
    ("email", "search"): fmt.format_email_list,
    ("calendar", "list"): fmt.format_calendar_event_list,
    ("calendar", "calendars"): fmt.format_calendar_name_list,
}


def _print_result(args, result) -> None:
    """Route a command result to the compact formatter or a JSON variant."""
    attrs = vars(args)
    want_json = "json" in attrs and attrs["json"]
    want_pretty = "json_pretty" in attrs and attrs["json_pretty"]

    if want_pretty:
        print(json.dumps(fmt.strip_odata(result), indent=2))
        return
    if want_json:
        print(json.dumps(fmt.strip_odata(result)))
        return

    formatter = _COMPACT_FORMATTERS[(args.group, args.command)] if (args.group, args.command) in _COMPACT_FORMATTERS else None
    if formatter is not None and isinstance(result, list):
        print(formatter(result))
        return

    print(json.dumps(fmt.strip_odata(result), indent=2))


def _dispatch_auth(args, config):
    if args.command == "list":
        return auth_commands.list_accounts(config)
    elif args.command == "login":
        return auth_commands.authenticate_account(config)
    elif args.command == "complete":
        return auth_commands.complete_authentication(config, flow_cache=args.flow_cache)
    elif args.command == "owa-login":
        return auth_commands.owa_login(config, account_email=args.account)


def _graph_has_account(config, account_email: str) -> bool:
    """True if the Graph token cache knows this account. Accounts on a locked tenant
    reachable only via OWA are absent here, so the Graph path can't resolve them."""
    try:
        return any((a["email"] or "").lower() == (account_email or "").lower() for a in auth_commands.list_accounts(config))
    except Exception:
        return False


def _dispatch_email(args, config, client):
    choice = getattr(args, "backend", backend.AUTO)

    def _owa_fn_for_auto(ews_fn, rest_fn, account_email: str):
        """For auto: try EWS; if that fails and a REST token is available, try REST."""

        def combined():
            try:
                return ews_fn()
            except Exception as exc:
                if owa_rest.has_valid_token(account_email, config):
                    return rest_fn()
                raise exc

        return combined

    def triple(graph_fn, ews_fn, rest_fn):
        if choice == backend.AUTO:
            # A captured OWA REST token for an account Graph doesn't know (locked
            # tenant) means Graph can't even resolve it: go straight to REST rather
            # than fail account resolution before the fallback can trigger.
            if owa_rest.has_valid_token(args.account, config) and not _graph_has_account(config, args.account):
                return rest_fn()
            return backend.run(backend.AUTO, graph_fn, _owa_fn_for_auto(ews_fn, rest_fn, args.account))
        return backend.run(choice, graph_fn, ews_fn, rest_fn)

    if args.command == "list":
        kw = dict(account_email=args.account, folder=args.folder, limit=args.limit)
        return triple(
            lambda: email.list_emails(config, client, **kw),
            lambda: owa_commands.list_emails(config, client, **kw),
            lambda: owa_rest_commands.list_emails(config, client, **kw),
        )
    elif args.command == "get":
        kw = dict(account_email=args.account, email_id=args.email_id, include_attachments=not args.no_attachments, save_to_file=args.save_to)
        return triple(
            lambda: email.get_email(config, client, **kw),
            lambda: owa_commands.get_email(config, client, **kw),
            lambda: owa_rest_commands.get_email(config, client, **kw),
        )
    elif args.command == "send":
        kw = dict(
            account_email=args.account,
            to=args.to,
            subject=args.subject,
            body=args.body,
            cc=args.cc,
            bcc=args.bcc,
            attachments=args.attachments,
            html=args.html,
        )
        return triple(
            lambda: email.send_email(config, client, **kw),
            lambda: owa_commands.send_email(config, client, **kw),
            lambda: owa_rest_commands.send_email(config, client, **kw),
        )
    elif args.command == "draft":
        kw = dict(
            account_email=args.account, to=args.to, subject=args.subject, body=args.body, cc=args.cc, bcc=args.bcc, attachments=args.attachments
        )
        return triple(
            lambda: email.create_email_draft(config, client, **kw),
            lambda: owa_commands.create_email_draft(config, client, **kw),
            lambda: owa_rest_commands.create_email_draft(config, client, **kw),
        )
    elif args.command == "reply":
        kw = dict(
            account_email=args.account,
            email_id=args.email_id,
            body=args.body,
            attachments=args.attachments,
            reply_all=args.reply_all,
            html=args.html,
        )
        return triple(
            lambda: email.reply_to_email(config, client, **kw),
            lambda: owa_commands.reply_to_email(config, client, **kw),
            lambda: owa_rest_commands.reply_to_email(config, client, **kw),
        )
    elif args.command == "attachment":
        kw = dict(account_email=args.account, email_id=args.email_id, attachment_id=args.attachment_id, save_path=args.save_path)
        return triple(
            lambda: email.get_attachment(config, client, **kw),
            lambda: owa_commands.get_attachment(config, client, **kw),
            lambda: owa_rest_commands.get_attachment(config, client, **kw),
        )
    elif args.command == "search":
        kw = dict(account_email=args.account, query=args.query, limit=args.limit, folder=args.folder)
        return triple(
            lambda: email.search_emails(config, client, **kw),
            lambda: owa_commands.search_emails(config, client, **kw),
            lambda: owa_rest_commands.search_emails(config, client, **kw),
        )
    elif args.command == "update":
        kw = dict(account_email=args.account, email_id=args.email_id, is_read=args.is_read, categories=args.categories)
        return triple(
            lambda: email.update_email(config, client, **kw),
            lambda: owa_commands.update_email(config, client, **kw),
            lambda: owa_rest_commands.update_email(config, client, **kw),
        )
    elif args.command == "delete":
        kw = dict(account_email=args.account, email_id=args.email_id, sender=args.sender, permanent=args.permanent)
        return triple(
            lambda: email.delete_email(config, client, **kw),
            lambda: owa_commands.delete_email(config, client, **kw),
            lambda: owa_rest_commands.delete_email(config, client, **kw),
        )
    elif args.command == "block":
        if args.list:
            return triple(
                lambda: block.list_block_rules(config, client, account_email=args.account),
                lambda: owa_commands.list_block_rules(config, client, account_email=args.account),
                lambda: owa_rest_commands.list_block_rules(config, client, account_email=args.account),
            )
        return triple(
            lambda: block.block_sender(config, client, account_email=args.account, sender=args.sender),
            lambda: owa_commands.block_sender(config, client, account_email=args.account, sender=args.sender),
            lambda: owa_rest_commands.block_sender(config, client, account_email=args.account, sender=args.sender),
        )
    elif args.command == "unblock":
        return triple(
            lambda: block.unblock_sender(config, client, account_email=args.account, sender=args.sender),
            lambda: owa_commands.unblock_sender(config, client, account_email=args.account, sender=args.sender),
            lambda: owa_rest_commands.unblock_sender(config, client, account_email=args.account, sender=args.sender),
        )


def _dispatch_calendar(args, config, client):
    choice = getattr(args, "backend", backend.AUTO)

    def _owa_fn_for_auto(ews_fn, rest_fn, account_email: str):
        def combined():
            try:
                return ews_fn()
            except Exception as exc:
                if owa_rest.has_valid_token(account_email, config):
                    return rest_fn()
                raise exc

        return combined

    def triple(graph_fn, ews_fn, rest_fn):
        if choice == backend.AUTO:
            # A captured OWA REST token for an account Graph doesn't know (locked
            # tenant) means Graph can't even resolve it: go straight to REST rather
            # than fail account resolution before the fallback can trigger.
            if owa_rest.has_valid_token(args.account, config) and not _graph_has_account(config, args.account):
                return rest_fn()
            return backend.run(backend.AUTO, graph_fn, _owa_fn_for_auto(ews_fn, rest_fn, args.account))
        return backend.run(choice, graph_fn, ews_fn, rest_fn)

    if args.command == "list":
        kw = dict(
            account_email=args.account,
            calendar_name=args.calendar_name,
            days_ahead=args.days_ahead,
            days_back=args.days_back,
            include_details=not args.no_details,
            user_timezone=args.user_timezone,
        )
        return triple(
            lambda: calendar.list_events(config, client, **kw),
            lambda: owa_commands.list_events(config, client, **kw),
            lambda: owa_rest_commands.list_events(config, client, **kw),
        )
    elif args.command == "calendars":
        return triple(
            lambda: calendar.list_calendars(config, client, account_email=args.account),
            lambda: owa_commands.list_calendars(config, client, account_email=args.account),
            lambda: owa_rest_commands.list_calendars(config, client, account_email=args.account),
        )
    elif args.command == "get":
        kw = dict(account_email=args.account, event_id=args.event_id)
        return triple(
            lambda: calendar.get_event(config, client, **kw),
            lambda: owa_commands.get_event(config, client, **kw),
            lambda: owa_rest_commands.get_event(config, client, **kw),
        )
    elif args.command == "create":
        kw = dict(
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
        return triple(
            lambda: calendar.create_event(config, client, **kw),
            lambda: owa_commands.create_event(config, client, **kw),
            lambda: owa_rest_commands.create_event(config, client, **kw),
        )
    elif args.command == "update":
        kw = dict(
            account_email=args.account,
            event_id=args.event_id,
            subject=args.subject,
            start=args.start,
            end=args.end,
            location=args.location,
            body=args.body,
            timezone=args.timezone,
        )
        return triple(
            lambda: calendar.update_event(config, client, **kw),
            lambda: owa_commands.update_event(config, client, **kw),
            lambda: owa_rest_commands.update_event(config, client, **kw),
        )
    elif args.command == "delete":
        kw = dict(account_email=args.account, event_id=args.event_id, send_cancellation=not args.no_cancellation)
        return triple(
            lambda: calendar.delete_event(config, client, **kw),
            lambda: owa_commands.delete_event(config, client, **kw),
            lambda: owa_rest_commands.delete_event(config, client, **kw),
        )
    elif args.command == "respond":
        kw = dict(account_email=args.account, event_id=args.event_id, response=args.response, message=args.message)
        return triple(
            lambda: calendar.respond_event(config, client, **kw),
            lambda: owa_commands.respond_event(config, client, **kw),
            lambda: owa_rest_commands.respond_event(config, client, **kw),
        )


def _run_serve(config: Config, notif_dir: Path):
    notif_dir.mkdir(parents=True, exist_ok=True)
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
        notif_dir=notif_dir,
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
        notifications.write_notification(notif_dir, "daemon_died", reason=shutdown_reason)
        _remove_pid(config)
        http_client.close()
