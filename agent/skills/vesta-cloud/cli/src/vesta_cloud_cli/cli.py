"""``vesta-cloud`` CLI entry point — the single authority for this box's Vesta Cloud
account: whether it has one, a credential to act as it, its plan, and its referral code.

The owner's own vesta runs this. `whoami` answers "do I have a Vesta Cloud account?"
(the discriminator every other skill keys off, NOT an env var); `token` hands out a
server-identity credential; `plan` / `manage` / `referral` mint that token from vestad
first (see `client.Client.mint_token`):

- ``vesta-cloud whoami``        — account? + plan/status + managed_infra + control_url (the env probe).
- ``vesta-cloud token``         — a short-lived server-identity token + control_url, for skills to call the control plane.
- ``vesta-cloud login``         — pair this self-hosted box to a Vesta Cloud account (owner approves a code).
- ``vesta-cloud logout``        — unpair this box from its Vesta Cloud account.
- ``vesta-cloud plan``          — this box's plan, price, status, renewal (a read).
- ``vesta-cloud manage``        — a Stripe-hosted link to upgrade / cancel / change card.
- ``vesta-cloud referral``      — this box's referral code, credit earned, invites completed.
- ``vesta-cloud set-referral``  — set/clear the code `onboard` sends on a completed invite.

Output is always JSON on stdout. Exit codes: 0 success, 2 surfaced {error}
(no account / no billing yet), 3 control-plane/vestad unreachable, 1 unexpected.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from . import referral_store
from .client import AccountError, Client
from .config import Config


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _cmd_whoami(_args: argparse.Namespace, client: Client, cfg: Config) -> int:
    """The environment probe every other skill keys off. `account` (does this box hold a
    Vesta Cloud account the control plane honors?) is the discriminator, NOT the
    `managed_infra` env signal, so a self-hosted box that holds an account answers
    `account: true` exactly like a managed VM. Always exit 0: "no account" is a valid
    answer, not an error (a genuine vestad/control-plane outage still raises -> exit 3)."""
    out: dict[str, Any] = {
        "account": False,
        "managed_infra": cfg.managed_infra,
        "control_url": cfg.control_url,
        "agent_name": cfg.agent_name or None,
    }
    minted = client.account_token()  # transport/5xx -> AccountError -> exit 3
    if not minted.get("token"):
        # A reached vestad refusing to mint = this box has no account (yet).
        out["reason"] = minted.get("error") or "no server-identity token"
        _print(out)
        return 0
    if minted.get("control_url"):
        # The identity names its control plane (e.g. a staging-paired box).
        out["control_url"] = minted["control_url"]
    summary = client.plan(minted["token"], minted.get("control_url"))  # transport -> exit 3
    if "error" in summary:
        # Recognized box, but no active membership (e.g. suspended / no billing).
        out["reason"] = summary["error"]
        _print(out)
        return 0
    out["account"] = True
    out["plan"] = summary.get("plan")
    out["status"] = summary.get("status")
    out["renews_at"] = summary.get("renews_at")
    cents = summary.get("price_cents")
    if isinstance(cents, int):
        out["price_usd"] = round(cents / 100, 2)
    _print(out)
    return 0


def _cmd_token(_args: argparse.Namespace, client: Client, cfg: Config) -> int:
    """Hand another skill a short-lived server-identity credential + the control-plane
    URL, so it calls the control plane as this server without re-implementing the mint.
    One general token works for any server-scoped route (/account, integrations, ...)."""
    detail = client.mint_token_detail()
    _print(
        {
            "token": detail["token"],
            "control_url": detail.get("control_url") or cfg.control_url,
            "expires_in": detail.get("expires_in"),
        }
    )
    return 0


def _cmd_login(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    """Pair this self-hosted box to a Vesta Cloud account (device authorization).
    Two-step output: first the code + link the agent must relay to the owner NOW,
    then (after the owner approves in their signed-in browser) a whoami-style
    confirmation. Blocks up to the code's ~10 minute lifetime."""
    started = client.pair_start()
    if "error" in started:
        _print(started)
        return 2
    _print(
        {
            "user_code": started.get("user_code"),
            "verification_url": started.get("verification_url"),
            "next": (
                "give the owner this code and link right away; they approve it in their "
                "signed-in browser. keep this command running, it returns once approved."
            ),
        }
    )
    sys.stdout.flush()

    interval = started.get("interval") if isinstance(started.get("interval"), int) else 5
    budget = started.get("expires_in") if isinstance(started.get("expires_in"), int) else 600
    deadline = time.monotonic() + budget
    while time.monotonic() < deadline:
        result = client.pair_poll()
        if result.get("status") == "linked":
            return _cmd_whoami(args, client, cfg)
        if "pending" in str(result.get("error") or ""):
            time.sleep(interval)
            continue
        # Terminal refusal (expired / account already has a server / unknown).
        _print(result)
        return 2
    _print(
        {
            "error": "pairing timed out",
            "message": "the code expired before the owner approved. run `vesta-cloud login` again for a fresh code.",
        }
    )
    return 2


def _cmd_logout(_args: argparse.Namespace, client: Client, _cfg: Config) -> int:
    """Unpair this box from its Vesta Cloud account. Also the local cleanup step when
    the owner already removed the box from the vesta.run dashboard."""
    result = client.unpair()
    if result.get("status") == "unpaired":
        _print(result)
        return 0
    _print(result)
    return 2


def _cmd_plan(_args: argparse.Namespace, client: Client, _cfg: Config) -> int:
    detail = client.mint_token_detail()
    summary = client.plan(detail["token"], detail.get("control_url"))
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


def _cmd_manage(_args: argparse.Namespace, client: Client, _cfg: Config) -> int:
    detail = client.mint_token_detail()
    result = client.portal(detail["token"], detail.get("control_url"))
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


def _cmd_referral(_args: argparse.Namespace, client: Client, _cfg: Config) -> int:
    try:
        detail = client.mint_token_detail()
    except AccountError:
        # A self-hosted box has no vesta-issued code; tell the agent what to do
        # instead of surfacing the raw mint-token error.
        _print(
            {
                "error": "not_hosted",
                "message": (
                    "This box has no Vesta Cloud account, so it has no vesta-issued referral code. "
                    "Ask the owner if they have one and set it with "
                    "`vesta-cloud set-referral --code <code>`."
                ),
            }
        )
        return 3
    summary = client.plan(detail["token"], detail.get("control_url"))
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


def _cmd_set_referral(args: argparse.Namespace, _client: Client, _cfg: Config) -> int:
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
        prog="vesta-cloud",
        description="This box's Vesta Cloud account: whoami + server-identity token, plan, billing, and referral code.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("whoami", help="Does this box have a Vesta Cloud account? + plan/status + managed_infra.")
    sub.add_parser("token", help="A short-lived server-identity token + control_url, for skills to call the control plane.")
    sub.add_parser("login", help="Pair this self-hosted box to a Vesta Cloud account (the owner approves a code).")
    sub.add_parser("logout", help="Unpair this box from its Vesta Cloud account.")
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
        "whoami": _cmd_whoami,
        "token": _cmd_token,
        "login": _cmd_login,
        "logout": _cmd_logout,
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
