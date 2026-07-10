"""Tricount CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn

from .client import TricountClient


def _out(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _err(msg: str) -> NoReturn:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Split parsing helpers
# ---------------------------------------------------------------------------


def _parse_weighted_split(raw: str) -> dict[str, float] | None:
    """Parse 'Alice=30,Bob=70' into {'Alice': 30.0, 'Bob': 70.0}.

    Returns None if the string contains no '=' (plain name list).
    """
    if "=" not in raw:
        return None
    result = {}
    for part in raw.split(","):
        part = part.strip()
        if "=" not in part:
            raise ValueError(f"Invalid weighted split entry '{part}': expected 'Name=Amount'")
        name, val = part.split("=", 1)
        try:
            result[name.strip()] = float(val.strip())
        except ValueError:
            raise ValueError(f"Invalid amount '{val.strip()}' for member '{name.strip()}'")
    return result


def _resolve_split_members(t, raw: str, active_members):
    """Resolve a comma-separated name/UUID list to Member objects."""
    names = [s.strip() for s in raw.split(",")]
    members = []
    for name in names:
        m = t.member_by_name(name) or t.member_by_uuid(name)
        if not m:
            _err(f"Split member '{name}' not found in this tricount")
        members.append(m)
    return members


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def cmd_auth_register(args: argparse.Namespace, client: TricountClient) -> dict:
    """Register this device with Tricount (no account needed)."""
    creds = client.authenticate()
    return {
        "status": "registered",
        "user_id": creds["user_id"],
        "app_installation_uuid": creds["app_installation_uuid"],
        "credentials_file": str(__import__("tricount_cli.config", fromlist=["CREDS_FILE"]).CREDS_FILE),
        "note": "Credentials saved. No Tricount account needed — this device is now an anonymous client.",
    }


def cmd_auth_status(args: argparse.Namespace, client: TricountClient) -> dict:
    return client.auth_status()


def cmd_auth_logout(args: argparse.Namespace, client: TricountClient) -> dict:
    result = client.logout()
    return {"status": "logged_out", "credentials_deleted": result["deleted"]}


def cmd_list(args: argparse.Namespace, client: TricountClient) -> list:
    tricounts = client.list_tricounts()
    return [
        {
            "id": t.id,
            "title": t.title,
            "currency": t.currency,
            "status": t.status,
            "token": t.public_identifier_token,
            "members": len(t.members),
            "expenses": len([tx for tx in t.transactions if tx.status == "ACTIVE"]),
        }
        for t in tricounts
    ]


def cmd_join(args: argparse.Namespace, client: TricountClient) -> dict:
    """Join a tricount by its public sharing token (e.g. 'tABC123')."""
    t = client.join_tricount(args.token)
    return {
        "status": "joined",
        "id": t.id,
        "title": t.title,
        "currency": t.currency,
        "token": t.public_identifier_token,
        "members": [{"name": m.display_name, "uuid": m.uuid, "status": m.status} for m in t.members],
    }


def cmd_show(args: argparse.Namespace, client: TricountClient) -> dict:
    """Show tricount details (members, summary)."""
    t = client.find_tricount(args.tricount)
    active_tx = [tx for tx in t.transactions if tx.status == "ACTIVE"]
    return {
        "id": t.id,
        "title": t.title,
        "currency": t.currency,
        "status": t.status,
        "token": t.public_identifier_token,
        "members": [{"name": m.display_name, "uuid": m.uuid, "status": m.status} for m in t.members],
        "expense_count": len(active_tx),
        "total": round(sum(tx.amount.abs_float for tx in active_tx if tx.tx_type == "NORMAL"), 2),
    }


def cmd_expenses(args: argparse.Namespace, client: TricountClient) -> list:
    """List all expenses in a tricount."""
    t = client.find_tricount(args.tricount)
    member_by_uuid = {m.uuid: m.display_name for m in t.members}
    result = []
    for tx in t.transactions:
        if tx.status != "ACTIVE":
            continue
        result.append(
            {
                "id": tx.id,
                "description": tx.description,
                "amount": tx.amount.abs_float,
                "currency": t.currency,
                "payer": member_by_uuid.get(tx.payer_uuid, tx.payer_uuid),
                "date": tx.date[:10] if tx.date else "",
                "type": tx.tx_type,
                "split": [
                    {
                        "member": member_by_uuid.get(a.membership_uuid, a.membership_uuid),
                        "amount": a.amount.abs_float,
                    }
                    for a in tx.allocations
                ],
            }
        )
    # Newest first
    result.sort(key=lambda x: x["date"], reverse=True)
    return result


def cmd_balances(args: argparse.Namespace, client: TricountClient) -> list:
    """Show net balances for each member of a tricount."""
    t = client.find_tricount(args.tricount)
    balances = client.get_balances(t)
    balances.sort(key=lambda x: x["balance"], reverse=True)
    return balances


def _resolve_add_expense_args(args, client, t):
    """Shared resolution logic for add-expense and edit-expense."""
    active_members = [m for m in t.members if m.status == "ACTIVE"]

    # Resolve payer (may be None for edit where payer is unchanged)
    payer_member = None
    if args.payer:
        payer_member = t.member_by_name(args.payer) or t.member_by_uuid(args.payer)
        if not payer_member:
            member_names = [m.display_name for m in active_members]
            _err(
                f"Payer '{args.payer}' not found. Members: {', '.join(member_names)}\n"
                "Tip: use the name exactly as shown in 'tricount show <tricount>'"
            )

    # Determine split mode
    amount_splits = None  # uuid -> float
    ratio_splits = None  # uuid -> float (shares)
    split_uuids = None
    split_members = []

    shares_raw = getattr(args, "shares", None)
    split_raw = getattr(args, "split", None)

    if shares_raw:
        # --shares "Alice=1,Bob=3" — proportional
        try:
            named = _parse_weighted_split(shares_raw)
        except ValueError as e:
            _err(str(e))
        if named is None:
            _err("--shares requires 'Name=weight' format, e.g. 'Alice=1,Bob=3'")
        ratio_splits = {}
        for name, weight in named.items():
            m = t.member_by_name(name) or t.member_by_uuid(name)
            if not m:
                _err(f"Member '{name}' not found in this tricount")
            ratio_splits[m.uuid] = weight
            split_members.append(m)
    elif split_raw:
        try:
            named = _parse_weighted_split(split_raw)
        except ValueError as e:
            _err(str(e))

        if named is not None:
            # --split "Alice=30,Bob=70" — fixed amounts
            amount_splits = {}
            for name, amt in named.items():
                m = t.member_by_name(name) or t.member_by_uuid(name)
                if not m:
                    _err(f"Member '{name}' not found in this tricount")
                amount_splits[m.uuid] = amt
                split_members.append(m)
        else:
            # --split "Alice,Bob" — equal split among named members
            split_members = _resolve_split_members(t, split_raw, active_members)
            split_uuids = [m.uuid for m in split_members]
    else:
        # Default: equal split among all active members (only for add-expense)
        split_members = active_members
        split_uuids = [m.uuid for m in split_members]

    return payer_member, split_members, split_uuids, amount_splits, ratio_splits


def cmd_add_expense(args: argparse.Namespace, client: TricountClient) -> dict:
    """Add an expense to a tricount.

    Payer and split members can be specified by name or UUID.

    Split modes:
      --split "Alice,Bob"       equal split among those members
      --split "Alice=30,Bob=70" fixed amounts (must sum to total)
      --shares "Alice=1,Bob=3"  proportional shares
      (omit both)                equal split among all active members
    """
    t = client.find_tricount(args.tricount)
    payer_member, split_members, split_uuids, amount_splits, ratio_splits = _resolve_add_expense_args(args, client, t)

    result = client.add_expense(
        tricount=t,
        description=args.description,
        amount=args.amount,
        payer_uuid=payer_member.uuid,
        split_uuids=split_uuids,
        amount_splits=amount_splits,
        ratio_splits=ratio_splits,
        date=args.date,
    )

    # Show the new expense ID from the response
    new_id = None
    for item in result.get("Response", []):
        if "Id" in item:
            new_id = item["Id"]["id"]

    split_desc = []
    if amount_splits:
        for m in split_members:
            split_desc.append(f"{m.display_name}={amount_splits[m.uuid]:.2f}")
    elif ratio_splits:
        for m in split_members:
            split_desc.append(f"{m.display_name}(share={ratio_splits[m.uuid]})")
    else:
        split_desc = [m.display_name for m in split_members]

    return {
        "status": "added",
        "id": new_id,
        "description": args.description,
        "amount": args.amount,
        "currency": t.currency,
        "payer": payer_member.display_name,
        "split": split_desc,
    }


def cmd_edit_expense(args: argparse.Namespace, client: TricountClient) -> dict:
    """Edit an existing expense in a tricount.

    Only the fields you provide will change; omitted fields keep their current values.
    """
    t = client.find_tricount(args.tricount)
    entry_id = args.expense_id

    # Find existing expense to validate it exists
    existing = t.transaction_by_id(entry_id)
    if existing is None:
        _err(f"Expense {entry_id} not found in tricount '{t.title}'")

    active_members = [m for m in t.members if m.status == "ACTIVE"]

    # Resolve payer if provided
    payer_uuid = None
    payer_name = None
    if args.payer:
        payer_member = t.member_by_name(args.payer) or t.member_by_uuid(args.payer)
        if not payer_member:
            member_names = [m.display_name for m in active_members]
            _err(f"Payer '{args.payer}' not found. Members: {', '.join(member_names)}")
        payer_uuid = payer_member.uuid
        payer_name = payer_member.display_name

    # Determine split mode
    amount_splits = None
    ratio_splits = None
    split_uuids = None
    split_desc = None

    shares_raw = getattr(args, "shares", None)
    split_raw = getattr(args, "split", None)

    if shares_raw:
        try:
            named = _parse_weighted_split(shares_raw)
        except ValueError as e:
            _err(str(e))
        if named is None:
            _err("--shares requires 'Name=weight' format, e.g. 'Alice=1,Bob=3'")
        ratio_splits = {}
        split_desc = []
        for name, weight in named.items():
            m = t.member_by_name(name) or t.member_by_uuid(name)
            if not m:
                _err(f"Member '{name}' not found in this tricount")
            ratio_splits[m.uuid] = weight
            split_desc.append(f"{m.display_name}(share={weight})")
    elif split_raw:
        try:
            named = _parse_weighted_split(split_raw)
        except ValueError as e:
            _err(str(e))
        if named is not None:
            amount_splits = {}
            split_desc = []
            for name, amt in named.items():
                m = t.member_by_name(name) or t.member_by_uuid(name)
                if not m:
                    _err(f"Member '{name}' not found in this tricount")
                amount_splits[m.uuid] = amt
                split_desc.append(f"{m.display_name}={amt:.2f}")
        else:
            split_members = _resolve_split_members(t, split_raw, active_members)
            split_uuids = [m.uuid for m in split_members]
            split_desc = [m.display_name for m in split_members]

    client.edit_expense(
        tricount=t,
        entry_id=entry_id,
        description=args.description,
        amount=args.amount,
        payer_uuid=payer_uuid,
        split_uuids=split_uuids,
        amount_splits=amount_splits,
        ratio_splits=ratio_splits,
        date=args.date,
    )

    member_by_uuid = {m.uuid: m.display_name for m in t.members}
    out = {
        "status": "updated",
        "id": entry_id,
        "description": args.description if args.description else existing.description,
        "amount": args.amount if args.amount is not None else existing.amount.abs_float,
        "currency": t.currency,
        "payer": payer_name if payer_name else member_by_uuid.get(existing.payer_uuid, existing.payer_uuid),
    }
    if split_desc:
        out["split"] = split_desc
    return out


def cmd_serve(args: argparse.Namespace, client: TricountClient) -> None:
    """Run the watcher daemon: poll all joined tricounts and emit notifications."""
    from . import watcher

    watcher.serve(Path(args.notifications_dir).expanduser(), interval=args.interval)


def cmd_delete_expense(args: argparse.Namespace, client: TricountClient) -> dict:
    """Delete an expense from a tricount."""
    t = client.find_tricount(args.tricount)
    entry_id = args.expense_id

    # Validate it exists before deleting
    existing = t.transaction_by_id(entry_id)
    if existing is None:
        _err(f"Expense {entry_id} not found in tricount '{t.title}'")

    client.delete_expense(tricount=t, entry_id=entry_id)
    return {
        "status": "deleted",
        "id": entry_id,
        "description": existing.description,
        "amount": existing.amount.abs_float,
        "currency": t.currency,
    }


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tricount",
        description="Unofficial Tricount CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- auth ---
    auth_parser = subparsers.add_parser("auth", help="Authentication / device registration")
    auth_sub = auth_parser.add_subparsers(dest="auth_command", required=True)

    auth_sub.add_parser(
        "register",
        help="Register this device (anonymous, no Tricount account needed)",
    ).set_defaults(func=cmd_auth_register)

    auth_sub.add_parser(
        "status",
        help="Show current auth status",
    ).set_defaults(func=cmd_auth_status)

    auth_sub.add_parser(
        "logout",
        help="Delete stored credentials",
    ).set_defaults(func=cmd_auth_logout)

    # --- list ---
    subparsers.add_parser(
        "list",
        help="List all tricounts this device has joined",
    ).set_defaults(func=cmd_list)

    # --- join ---
    join_p = subparsers.add_parser(
        "join",
        help="Join a tricount by its public sharing token (e.g. tABC123)",
    )
    join_p.add_argument(
        "token",
        help="Public identifier token (the 'tXXX...' code from the sharing URL)",
    )
    join_p.set_defaults(func=cmd_join)

    # --- show ---
    show_p = subparsers.add_parser(
        "show",
        help="Show tricount details and members",
    )
    show_p.add_argument(
        "tricount",
        help="Tricount ID (numeric) or public token or title",
    )
    show_p.set_defaults(func=cmd_show)

    # --- expenses ---
    exp_p = subparsers.add_parser(
        "expenses",
        help="List all expenses in a tricount",
    )
    exp_p.add_argument(
        "tricount",
        help="Tricount ID (numeric) or public token or title",
    )
    exp_p.set_defaults(func=cmd_expenses)

    # --- balances ---
    bal_p = subparsers.add_parser(
        "balances",
        help="Show net balances for each member",
    )
    bal_p.add_argument(
        "tricount",
        help="Tricount ID (numeric) or public token or title",
    )
    bal_p.set_defaults(func=cmd_balances)

    # --- add-expense ---
    add_p = subparsers.add_parser(
        "add-expense",
        help="Add an expense to a tricount",
    )
    add_p.add_argument(
        "tricount",
        help="Tricount ID (numeric) or public token or title",
    )
    add_p.add_argument(
        "--description",
        "-d",
        required=True,
        help="Expense description (e.g. 'Dinner')",
    )
    add_p.add_argument(
        "--amount",
        "-a",
        type=float,
        required=True,
        help="Total amount as a positive number (e.g. 50.00)",
    )
    add_p.add_argument(
        "--payer",
        "-p",
        required=True,
        help="Name (or UUID) of the member who paid",
    )
    add_p.add_argument(
        "--split",
        "-s",
        default=None,
        help=(
            "How to split the expense. Options:\n"
            "  'Alice,Bob'       — equal split among named members\n"
            "  'Alice=30,Bob=70' — fixed amounts (must sum to total)\n"
            "  (omit)             — equal split among all active members"
        ),
    )
    add_p.add_argument(
        "--shares",
        default=None,
        help=(
            "Proportional share split, e.g. 'Alice=1,Bob=3' means Bob pays 3x Alice's share. "
            "Amounts are computed from the total proportionally."
        ),
    )
    add_p.add_argument(
        "--date",
        default=None,
        help="Date in 'YYYY-MM-DD HH:MM:SS.000000' format (default: now)",
    )
    add_p.set_defaults(func=cmd_add_expense)

    # --- edit-expense ---
    edit_p = subparsers.add_parser(
        "edit-expense",
        help="Edit an existing expense (change description, amount, payer, or split)",
    )
    edit_p.add_argument(
        "tricount",
        help="Tricount ID (numeric) or public token or title",
    )
    edit_p.add_argument(
        "expense_id",
        type=int,
        help="Numeric ID of the expense to edit (see 'tricount expenses <tricount>')",
    )
    edit_p.add_argument(
        "--description",
        "-d",
        default=None,
        help="New description (leave out to keep existing)",
    )
    edit_p.add_argument(
        "--amount",
        "-a",
        type=float,
        default=None,
        help="New total amount (leave out to keep existing)",
    )
    edit_p.add_argument(
        "--payer",
        "-p",
        default=None,
        help="New payer name or UUID (leave out to keep existing)",
    )
    edit_p.add_argument(
        "--split",
        "-s",
        default=None,
        help=(
            "New split. Options:\n"
            "  'Alice,Bob'       — equal split among named members\n"
            "  'Alice=30,Bob=70' — fixed amounts\n"
            "  (omit)             — keep existing split (scaled if amount changed)"
        ),
    )
    edit_p.add_argument(
        "--shares",
        default=None,
        help="New proportional share split, e.g. 'Alice=1,Bob=3'",
    )
    edit_p.add_argument(
        "--date",
        default=None,
        help="New date in 'YYYY-MM-DD HH:MM:SS.000000' format",
    )
    edit_p.set_defaults(func=cmd_edit_expense)

    # --- delete-expense ---
    del_p = subparsers.add_parser(
        "delete-expense",
        help="Delete an expense from a tricount",
    )
    del_p.add_argument(
        "tricount",
        help="Tricount ID (numeric) or public token or title",
    )
    del_p.add_argument(
        "expense_id",
        type=int,
        help="Numeric ID of the expense to delete (see 'tricount expenses <tricount>')",
    )
    del_p.set_defaults(func=cmd_delete_expense)

    # --- serve (watcher daemon) ---
    serve_p = subparsers.add_parser(
        "serve",
        help="Run the watcher daemon: poll all joined tricounts and emit notifications on changes",
    )
    serve_p.add_argument(
        "--notifications-dir",
        required=True,
        help="Directory to write notification JSON files into (e.g. ~/agent/notifications)",
    )
    serve_p.add_argument(
        "--interval",
        type=int,
        default=120,
        help="Seconds between polls (default: 120; be gentle on the API)",
    )
    serve_p.set_defaults(func=cmd_serve)

    args = parser.parse_args()

    client = TricountClient()

    # auth register doesn't need existing creds
    try:
        result = args.func(args, client)
        if result is not None:
            _out(result)
    except KeyboardInterrupt:
        sys.exit(0)
    except RuntimeError as e:
        _err(str(e))
    except Exception as e:
        _err(f"Unexpected error: {e}")
