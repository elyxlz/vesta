"""``stripe-pay`` CLI entry point.

Two subcommands:
- ``stripe-pay authorize`` — one-time OAuth setup against Link Wallet for Agents.
- ``stripe-pay charge``    — request a charge with per-charge user approval.

Output is always JSON on stdout; human-readable progress goes to stderr. Exit
codes:
- 0 on success or successful rejection (rejection is a normal outcome)
- 2 on invalid input
- 3 on auth failures
- 4 on timeout
- 1 on unexpected errors
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import auth as auth_mod
from . import charge as charge_mod
from .config import Config


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _cmd_authorize(args: argparse.Namespace, config: Config) -> int:
    try:
        result = auth_mod.authorize(config, open_browser=not args.no_browser)
    except auth_mod.AuthError as e:
        _print({"status": "error", "error": "auth_error", "message": str(e)})
        return 3
    _print(result)
    return 0


def _cmd_status(args: argparse.Namespace, config: Config) -> int:
    _print(auth_mod.status(config))
    return 0


def _cmd_charge(args: argparse.Namespace, config: Config) -> int:
    try:
        result = charge_mod.charge(
            config,
            amount=args.amount,
            currency=args.currency,
            merchant=args.merchant,
            reason=args.reason,
            timeout_s=args.timeout,
        )
    except ValueError as e:
        _print({"status": "error", "error": "invalid_input", "message": str(e)})
        return 2
    except auth_mod.AuthError as e:
        _print({"status": "error", "error": "auth_error", "message": str(e)})
        return 3
    _print(result)
    if result["status"] == "approved":
        return 0
    if result["status"] == "rejected":
        return 0
    if result["status"] == "timeout":
        return 4
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stripe-pay",
        description="Stripe Link Wallet for Agents — per-charge approval CLI for vesta.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # authorize
    p_auth = sub.add_parser("authorize", help="One-time OAuth setup against Link.")
    p_auth.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the authorize URL but don't try to open it. Useful on headless boxes.",
    )

    # status
    sub.add_parser("status", help="Print current OAuth status (no network call beyond local).")

    # charge
    p_charge = sub.add_parser("charge", help="Request a single charge with user approval.")
    p_charge.add_argument("--amount", type=float, required=True, help="Major-units amount (e.g. 24.99).")
    p_charge.add_argument("--currency", required=True, help="ISO 4217 currency code, e.g. USD.")
    p_charge.add_argument("--merchant", required=True, help="Merchant name shown to the user.")
    p_charge.add_argument("--reason", required=True, help="Why the agent wants this charge — shown to the user verbatim.")
    p_charge.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for user approval. Default: 300 (5 minutes).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    config = Config()

    handlers = {
        "authorize": _cmd_authorize,
        "status": _cmd_status,
        "charge": _cmd_charge,
    }
    handler = handlers.get(args.command)
    if not handler:
        parser.error(f"unknown command: {args.command}")
    try:
        return handler(args, config)
    except KeyboardInterrupt:
        _print({"status": "error", "error": "interrupted"})
        return 130
    except Exception as e:  # last-resort net so the CLI never explodes raw
        _print(
            {
                "status": "error",
                "error": type(e).__name__,
                "message": str(e),
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
