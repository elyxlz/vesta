"""``onboard`` CLI entry point.

Subcommands:
- ``onboard check <subdomain>``   — is they.vesta.run free?
- ``onboard start ...``           — reserve + mint a Stripe Checkout link.
- ``onboard status --subdomain``  — has signup gone through yet?
- ``onboard presets``             — personality presets + installable skills.
- ``onboard links``               — marketing + install URLs.

Output is always JSON on stdout; human-readable errors go through the same JSON
(`{"error": ...}`). Exit codes: 0 success, 2 invalid input, 3 control-plane
unreachable/error, 1 unexpected.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .client import Client, OnboardError
from .config import LINKS, PERSONALITY_PRESETS, PLAN_FLOOR_USD, PLANS, Config


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _cmd_check(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    _print(client.check(args.subdomain.strip().lower()))
    return 0


def _cmd_start(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    plan = args.plan.strip().lower()
    if plan not in PLANS:
        _print({"error": f"plan must be one of {', '.join(PLANS)}"})
        return 2
    # Negotiated price (optional). Floor = the plan's list price; uncapped above.
    price: float | None = None
    if args.price is not None:
        floor = PLAN_FLOOR_USD[plan]
        if args.price < floor:
            _print(
                {
                    "error": f"price ${args.price:g} is below the {plan} floor of ${floor}",
                    "floor_usd": floor,
                }
            )
            return 2
        price = args.price
    seed: dict[str, Any] = {}
    if args.name:
        seed["name"] = args.name.strip()
    if args.personality:
        seed["personality"] = args.personality.strip().lower()
    if args.skills:
        skills = [s.strip() for s in args.skills.split(",") if s.strip()]
        if skills:
            seed["skills"] = skills
    result = client.checkout(
        email=args.email.strip(),
        subdomain=args.subdomain.strip().lower(),
        plan=plan,
        seed=seed or None,
        # explicit --referral wins; otherwise the env-derived code (hosted only)
        referral_code=args.referral or cfg.referral_code,
        price=price,
        code=(args.code.strip() if args.code else None),
    )
    _print(result)
    # A structured {error} (taken/rate-limited) is a normal, surfaced outcome.
    return 0 if "url" in result else 2


def _cmd_status(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    """No dedicated status endpoint exists; infer from subdomain availability.

    Free (available) → nobody has signed up with it yet (`pending`); taken →
    signup went through (`signed_up`). This is the signal the introducer needs:
    "did they complete checkout?".
    """
    res = client.check(args.subdomain.strip().lower())
    sub = res.get("subdomain", args.subdomain)
    if res.get("available") is True:
        status = "pending"
    elif res.get("reason") == "taken":
        status = "signed_up"
    else:
        status = res.get("reason", "unknown")
    _print({"subdomain": sub, "status": status})
    return 0


def _installable_skills() -> list[str]:
    """Best-effort list of skill names from the on-box skills index."""
    for p in (
        Path.home() / "agent" / "skills" / "index.json",
        Path("/root/agent/skills/index.json"),
        Path(__file__).resolve().parents[4] / "index.json",
    ):
        try:
            if p.exists():
                data = json.loads(p.read_text())
                return sorted(s.get("name", "") for s in data if s.get("name"))
        except (OSError, ValueError):
            continue
    return []


def _cmd_presets(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    _print(
        {
            "personalities": list(PERSONALITY_PRESETS),
            "skills": _installable_skills(),
            "plans": list(PLANS),
            # Negotiation floor (USD/mo) per plan; quote >= these, uncapped above.
            "plan_floor_usd": PLAN_FLOOR_USD,
        }
    )
    return 0


def _cmd_links(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    _print(LINKS)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="onboard",
        description="Introduce a stranger to Vesta and mint a signup checkout link.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="Is a subdomain available?")
    p_check.add_argument("subdomain", help="The desired <name>.vesta.run label.")

    p_start = sub.add_parser("start", help="Reserve + mint a Stripe Checkout link.")
    p_start.add_argument("--email", required=True, help="Prospective member's email.")
    p_start.add_argument("--subdomain", required=True, help="Desired <name>.vesta.run label.")
    # One plan today (the standard box, cx33). Kept as a hidden knob defaulting to
    # `pro` so the plumbing supports more tiers later without the agent picking one.
    p_start.add_argument("--plan", default="pro", help=argparse.SUPPRESS)
    p_start.add_argument("--name", help="Optional agent name to seed at first boot.")
    p_start.add_argument("--personality", help="Optional personality preset (see `onboard presets`).")
    p_start.add_argument("--skills", help="Optional comma-separated starting skills.")
    p_start.add_argument(
        "--price",
        type=float,
        help="Negotiated MONTHLY price in USD. Floor = plan list price; uncapped above. Omit for list price.",
    )
    p_start.add_argument("--referral", help="Override the referral code (defaults to $VESTA_REFERRAL_CODE).")
    p_start.add_argument("--code", help="Optional discount code to redeem at checkout (e.g. a 50%%-off invite code).")

    p_status = sub.add_parser("status", help="Has signup gone through yet?")
    p_status.add_argument("--subdomain", required=True, help="The subdomain to check.")

    sub.add_parser("presets", help="Personality presets + installable skills.")
    sub.add_parser("links", help="Marketing + desktop/mobile install URLs.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    cfg = Config.load()
    client = Client(cfg)

    handlers = {
        "check": _cmd_check,
        "start": _cmd_start,
        "status": _cmd_status,
        "presets": _cmd_presets,
        "links": _cmd_links,
    }
    handler = handlers[args.command]
    try:
        return handler(args, client, cfg)
    except OnboardError as e:
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
