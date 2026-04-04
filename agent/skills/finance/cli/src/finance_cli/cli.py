"""finance — Enable Banking CLI for personal finance tracking.

Commands:
  finance config set --app-id <uuid> --key-path <path-to-pem>
  finance config show

  finance auth login          # print URL, start local server, exchange code
  finance auth status         # check if session is active
  finance auth revoke         # delete session

  finance accounts            # list connected accounts
  finance balances            # show balances for all accounts

  finance transactions list [--days N] [--from YYYY-MM-DD] [--to YYYY-MM-DD]

  finance summary [--month YYYY-MM] [--days N] [--from YYYY-MM-DD] [--to YYYY-MM-DD]
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, UTC

from . import config as cfg
from . import enablebanking as eb


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


def _month_range(month_str: str) -> tuple[datetime, datetime]:
    """Return (start, end) datetimes for a YYYY-MM month string."""
    dt = datetime.strptime(month_str, "%Y-%m").replace(tzinfo=UTC)
    from_dt = dt
    if dt.month == 12:
        to_dt = dt.replace(year=dt.year + 1, month=1)
    else:
        to_dt = dt.replace(month=dt.month + 1)
    return from_dt, to_dt


def _resolve_date_range(args, default_days: int = 30) -> tuple[datetime, datetime]:
    """Resolve --from/--to or --days into (from_dt, to_dt)."""
    now = datetime.now(UTC)
    if hasattr(args, "from_date") and args.from_date:
        from_dt = _parse_date(args.from_date)
    elif hasattr(args, "days") and args.days:
        from_dt = now - timedelta(days=args.days)
    else:
        from_dt = now - timedelta(days=default_days)

    if hasattr(args, "to_date") and args.to_date:
        to_dt = _parse_date(args.to_date)
    else:
        to_dt = now

    return from_dt, to_dt


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def cmd_config_set(args) -> dict:
    conf = cfg.load()
    if args.app_id:
        conf["app_id"] = args.app_id
    if args.key_path:
        conf["key_path"] = args.key_path
    cfg.save(conf)
    return {
        "status": "saved",
        "config": {
            "app_id": conf.get("app_id", ""),
            "key_path": conf.get("key_path", ""),
            "session_id": "***" if conf.get("session_id") else "",
            "accounts_count": len(conf.get("accounts", [])),
        },
    }


def cmd_config_show(args) -> dict:
    conf = cfg.load()
    return {
        "app_id": conf.get("app_id", ""),
        "key_path": conf.get("key_path", ""),
        "session_id": "***" if conf.get("session_id") else "",
        "accounts": conf.get("accounts", []),
    }


def cmd_auth_login(args) -> dict:
    conf = cfg.load()
    cfg.require_credentials(conf)

    print(json.dumps({"status": "initiating", "message": "Contacting Enable Banking..."}), flush=True)

    auth_url, state = eb.initiate_auth(conf)

    print(
        json.dumps(
            {
                "action": "visit_url",
                "message": "Open this URL in your browser to authorise bank access:",
                "url": auth_url,
                "waiting": f"Listening on https://localhost:{eb.CALLBACK_PORT}{eb.CALLBACK_PATH} for the callback...",
                "fallback": "If the browser shows an SSL error, copy the full URL from the address bar and run: finance auth callback --url '<url>'",
            }
        ),
        flush=True,
    )

    # Block until callback received
    code = eb.wait_for_callback(eb.CALLBACK_PORT)

    print(json.dumps({"status": "code_received", "message": "Authorization code received, creating session..."}), flush=True)

    session_data = eb.exchange_code(conf, code)

    session_id = session_data.get("session_id", "")
    raw_accounts = session_data.get("accounts", [])

    # Normalise account list for storage
    accounts = []
    for acc in raw_accounts:
        accounts.append(
            {
                "uid": acc.get("uid", acc.get("account_uid", "")),
                "name": acc.get("name", acc.get("account_id", {}).get("iban", "unknown")),
                "currency": acc.get("currency", ""),
            }
        )

    conf["session_id"] = session_id
    conf["accounts"] = accounts
    cfg.save(conf)

    return {
        "status": "authenticated",
        "session_id": session_id,
        "accounts": accounts,
        "consent_days": eb.CONSENT_DAYS,
    }


def cmd_auth_callback(args) -> dict:
    """Manual fallback: paste the redirect URL to complete auth if auto-catch failed."""
    conf = cfg.load()
    cfg.require_credentials(conf)

    import urllib.parse

    parsed = urllib.parse.urlparse(args.url)
    qs = urllib.parse.parse_qs(parsed.query)

    if "error" in qs:
        return {"error": qs["error"][0], "description": qs.get("error_description", [""])[0]}

    code = qs.get("code", [None])[0]
    if not code:
        return {"error": "No 'code' parameter found in URL"}

    session_data = eb.exchange_code(conf, code)

    session_id = session_data.get("session_id", "")
    raw_accounts = session_data.get("accounts", [])

    accounts = []
    for acc in raw_accounts:
        accounts.append(
            {
                "uid": acc.get("uid", acc.get("account_uid", "")),
                "name": acc.get("name", acc.get("account_id", {}).get("iban", "unknown")),
                "currency": acc.get("currency", ""),
            }
        )

    conf["session_id"] = session_id
    conf["accounts"] = accounts
    cfg.save(conf)

    return {
        "status": "authenticated",
        "session_id": session_id,
        "accounts": accounts,
        "consent_days": eb.CONSENT_DAYS,
    }


def cmd_auth_status(args) -> dict:
    conf = cfg.load()
    has_creds = bool(conf.get("app_id") and conf.get("key_path"))
    has_session = bool(conf.get("session_id"))

    result: dict = {
        "credentials_configured": has_creds,
        "session_active": has_session,
        "app_id": conf.get("app_id", ""),
        "key_path": conf.get("key_path", ""),
        "accounts_count": len(conf.get("accounts", [])),
    }

    if has_session and has_creds:
        try:
            session = eb.get_session(conf)
            result["session_status"] = session.get("status", "unknown")
            result["valid_until"] = session.get("access", {}).get("valid_until", "")
        except SystemExit:
            result["session_status"] = "error_fetching"

    return result


def cmd_auth_revoke(args) -> dict:
    conf = cfg.load()
    cfg.require_session(conf)

    eb.revoke_session(conf)

    conf["session_id"] = ""
    conf["accounts"] = []
    cfg.save(conf)

    return {"status": "revoked", "message": "Session deleted and local credentials cleared."}


def cmd_accounts(args) -> list:
    conf = cfg.load()
    cfg.require_session(conf)
    accounts = conf.get("accounts", [])
    if not accounts:
        return []
    return accounts


def cmd_balances(args) -> list:
    conf = cfg.load()
    cfg.require_session(conf)

    accounts = conf.get("accounts", [])
    results = []
    for acc in accounts:
        uid = acc.get("uid", "")
        if not uid:
            continue
        try:
            balances = eb.get_balances(conf, uid)
        except SystemExit:
            balances = [{"error": "could not fetch balance"}]
        results.append(
            {
                "uid": uid,
                "name": acc.get("name", ""),
                "currency": acc.get("currency", ""),
                "balances": balances,
            }
        )
    return results


def cmd_transactions_list(args) -> list:
    conf = cfg.load()
    cfg.require_session(conf)

    from_dt, to_dt = _resolve_date_range(args)
    accounts = conf.get("accounts", [])

    all_txns = []
    for acc in accounts:
        uid = acc.get("uid", "")
        if not uid:
            continue
        txns = eb.get_transactions(
            conf,
            uid,
            date_from=_fmt_date(from_dt),
            date_to=_fmt_date(to_dt),
        )
        for tx in txns:
            tx["_account_uid"] = uid
            tx["_account_name"] = acc.get("name", "")
        all_txns.extend(txns)

    # Sort newest first — Enable Banking uses booking_date or value_date
    all_txns.sort(
        key=lambda t: t.get("booking_date") or t.get("value_date") or "",
        reverse=True,
    )
    return all_txns


def cmd_summary(args) -> dict:
    conf = cfg.load()
    cfg.require_session(conf)

    if hasattr(args, "month") and args.month:
        from_dt, to_dt = _month_range(args.month)
    else:
        from_dt, to_dt = _resolve_date_range(args)

    accounts = conf.get("accounts", [])
    all_txns = []
    for acc in accounts:
        uid = acc.get("uid", "")
        if not uid:
            continue
        txns = eb.get_transactions(
            conf,
            uid,
            date_from=_fmt_date(from_dt),
            date_to=_fmt_date(to_dt),
        )
        all_txns.extend(txns)

    summary = eb.aggregate_by_category(all_txns)
    summary["period"] = {
        "from": _fmt_date(from_dt),
        "to": _fmt_date(to_dt),
    }
    return summary


# ---------------------------------------------------------------------------
# Main / parser
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(prog="finance", description="Enable Banking finance CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- config ---
    p_config = sub.add_parser("config", help="Manage configuration")
    config_sub = p_config.add_subparsers(dest="config_command", required=True)

    p_config_set = config_sub.add_parser("set", help="Set configuration values")
    p_config_set.add_argument("--app-id", dest="app_id", default=None, help="Enable Banking application UUID")
    p_config_set.add_argument("--key-path", dest="key_path", default=None, help="Path to RS256 private key PEM file")

    config_sub.add_parser("show", help="Show current configuration")

    # --- auth ---
    p_auth = sub.add_parser("auth", help="Authentication commands")
    auth_sub = p_auth.add_subparsers(dest="auth_command", required=True)

    auth_sub.add_parser(
        "login",
        help="Start bank auth: prints URL, listens for callback, creates session",
    )
    p_auth_callback = auth_sub.add_parser(
        "callback",
        help="Manual fallback: paste redirect URL if auto-catch failed",
    )
    p_auth_callback.add_argument("--url", required=True, help="Full redirect URL from browser")
    auth_sub.add_parser("status", help="Show authentication / session status")
    auth_sub.add_parser("revoke", help="Delete the active session")

    # --- accounts ---
    sub.add_parser("accounts", help="List connected accounts (from stored session)")

    # --- balances ---
    sub.add_parser("balances", help="Show current balances for all accounts")

    # --- transactions ---
    p_txn = sub.add_parser("transactions", help="Transaction commands")
    txn_sub = p_txn.add_subparsers(dest="transactions_command", required=True)

    p_txn_list = txn_sub.add_parser("list", help="List recent transactions")
    p_txn_list.add_argument("--days", type=int, default=None, help="Number of days back (default: 30)")
    p_txn_list.add_argument("--from", dest="from_date", default=None, metavar="YYYY-MM-DD")
    p_txn_list.add_argument("--to", dest="to_date", default=None, metavar="YYYY-MM-DD")

    # --- summary ---
    p_summary = sub.add_parser("summary", help="Spending summary grouped by merchant/category")
    p_summary.add_argument("--month", default=None, metavar="YYYY-MM", help="Specific month (e.g. 2026-03)")
    p_summary.add_argument("--days", type=int, default=None, help="Number of days back (default: 30)")
    p_summary.add_argument("--from", dest="from_date", default=None, metavar="YYYY-MM-DD")
    p_summary.add_argument("--to", dest="to_date", default=None, metavar="YYYY-MM-DD")

    args = parser.parse_args()

    try:
        result = _dispatch(args)
        print(json.dumps(result, indent=2))
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


def _dispatch(args):
    cmd = args.command

    if cmd == "config":
        if args.config_command == "set":
            return cmd_config_set(args)
        elif args.config_command == "show":
            return cmd_config_show(args)

    elif cmd == "auth":
        if args.auth_command == "login":
            return cmd_auth_login(args)
        elif args.auth_command == "callback":
            return cmd_auth_callback(args)
        elif args.auth_command == "status":
            return cmd_auth_status(args)
        elif args.auth_command == "revoke":
            return cmd_auth_revoke(args)

    elif cmd == "accounts":
        return cmd_accounts(args)

    elif cmd == "balances":
        return cmd_balances(args)

    elif cmd == "transactions":
        if args.transactions_command == "list":
            return cmd_transactions_list(args)

    elif cmd == "summary":
        return cmd_summary(args)

    raise ValueError(f"Unknown command: {cmd}")
