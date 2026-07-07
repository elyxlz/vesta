"""``vesta-cloud-account`` CLI entry point — read this box's plan, facilitate
billing changes, and manage the referral code the `onboard` skill uses.

The owner's own vesta runs this to answer account questions and hand over a
secure management link. `plan`, `manage`, and `referral` all mint a fresh
server-identity token from vestad first (see `client.Client.mint_token`):

- ``vesta-cloud-account plan``          — this box's plan, price, status, renewal (a read).
- ``vesta-cloud-account manage``        — a Stripe-hosted link to upgrade / cancel / change card.
- ``vesta-cloud-account referral``      — this box's referral code, credit earned, invites completed.
- ``vesta-cloud-account set-referral``  — set/clear the code `onboard` sends on a completed invite.

Output is always JSON on stdout. Exit codes: 0 success, 2 surfaced {error}
(self-hosted box, no billing account yet), 3 control-plane/vestad unreachable,
1 unexpected.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from . import referral_store
from .client import AccountError, Client
from .config import Config


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _cmd_plan(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    token = client.mint_token()
    summary = client.plan(token)
    if "error" in summary:
        _print(summary)
        return 2
    # Add a friendly dollar figure alongside the raw cents so the agent can quote
    # a price without doing arithmetic; leave everything else as the control plane
    # returned it.
    cents = summary.get("price_cents")
    if isinstance(cents, int):
        summary = {**summary, "price_usd": round(cents / 100, 2)}
    _print(summary)
    return 0


def _cmd_manage(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    token = client.mint_token()
    result = client.portal(token)
    if "url" not in result:
        # e.g. {"error": "no_billing_account"} — never completed checkout.
        _print(result)
        return 2
    _print(
        {
            "url": result["url"],
            "next": "give the owner this link to upgrade, change payment, or cancel — they confirm it there; you don't",
        }
    )
    return 0


def _cmd_referral(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    try:
        token = client.mint_token()
    except AccountError:
        # A self-hosted box has no vesta-issued code; tell the agent what to do
        # instead of surfacing the raw mint-token error.
        _print(
            {
                "error": "not_hosted",
                "message": (
                    "This box is not cloud-managed, so it has no vesta-issued referral code. "
                    "Ask the owner if they have one and set it with "
                    "`vesta-cloud-account set-referral --code <code>`."
                ),
            }
        )
        return 3
    summary = client.plan(token)
    if "error" in summary:
        _print(summary)
        return 2
    _print(
        {
            "referral_code": summary.get("referral_code"),
            "referral_credit_cents": summary.get("referral_credit_cents"),
            "invites_completed": summary.get("invites_completed"),
        }
    )
    return 0


def _cmd_set_referral(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    if args.clear:
        referral_store.clear_referral_code()
        _print({"ok": True, "referral_code": None})
        return 0
    code = args.code.strip()
    referral_store.set_referral_code(code)
    _print({"ok": True, "referral_code": code})
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vesta-cloud-account",
        description="Read this box's Vesta hosting plan, facilitate billing changes, and manage its referral code.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="This box's plan, price, status, and renewal date.")
    sub.add_parser("manage", help="A secure Stripe link to upgrade / cancel / change payment.")
    sub.add_parser("referral", help="This box's referral code, credit earned, and invites completed.")
    p_set = sub.add_parser("set-referral", help="Set or clear the referral code the `onboard` skill sends.")
    group = p_set.add_mutually_exclusive_group(required=True)
    group.add_argument("--code", help="The referral code to persist.")
    group.add_argument("--clear", action="store_true", help="Remove the stored referral code.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    cfg = Config.load()
    client = Client(cfg)

    handlers = {
        "plan": _cmd_plan,
        "manage": _cmd_manage,
        "referral": _cmd_referral,
        "set-referral": _cmd_set_referral,
    }
    handler = handlers[args.command]
    try:
        return handler(args, client, cfg)
    except AccountError as e:
        _print({"error": str(e)})
        return 3
    except KeyboardInterrupt:
        _print({"error": "interrupted"})
        return 130
    except Exception as e:  # last-resort net so the CLI never explodes raw
        _print({"error": type(e).__name__, "message": str(e)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
