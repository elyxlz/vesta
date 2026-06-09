"""``account`` CLI entry point — read this box's plan, facilitate billing changes.

The owner's own vesta runs this to answer account questions and hand over a
secure management link. Both commands mint a fresh server-identity token from
vestad first (see `client.Client.mint_token`):

- ``account plan``    — this box's plan, price, status, renewal (a read).
- ``account manage``  — a Stripe-hosted link to upgrade / cancel / change card.

Output is always JSON on stdout. Exit codes: 0 success, 2 surfaced {error}
(self-hosted box, no billing account yet), 3 control-plane/vestad unreachable,
1 unexpected.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="account",
        description="Read this box's Vesta hosting plan and facilitate billing changes.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="This box's plan, price, status, and renewal date.")
    sub.add_parser("manage", help="A secure Stripe link to upgrade / cancel / change payment.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    cfg = Config.load()
    client = Client(cfg)

    handlers = {
        "plan": _cmd_plan,
        "manage": _cmd_manage,
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
