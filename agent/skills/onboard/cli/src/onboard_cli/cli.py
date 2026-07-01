"""``onboard`` CLI entry point — the conduit onboarding flow.

The agent (an existing member's vesta) walks a stranger in, in conversation. Each
step is a subcommand; the buyer's verified session persists between invocations
(`state.py`), so after the OTP the CLI acts AS the buyer:

- ``onboard verify-send --email``    — email the buyer a 6-digit code.
- ``onboard verify --email --code``  — the code they read back -> their session.
- ``onboard checkout --email``       — reserve + mint a Stripe link (auto subdomain).
- ``onboard status --email``         — has the VM come up yet?
- ``onboard create-agent --email``   — create their first agent (name/personality/skills).
- ``onboard claude-start --email``   — begin Claude connect -> an auth link.
- ``onboard claude-finish --email``  — the code they paste back -> agent alive.
- ``onboard presets`` / ``onboard links`` — reference data.

Output is always JSON on stdout. Exit codes: 0 success, 2 invalid input / surfaced
{error}, 3 control-plane/vestad unreachable, 1 unexpected.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import state
from .client import Client, OnboardError
from .config import LINKS, PLAN, PLAN_FLOOR_USD, Config


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _email(args: argparse.Namespace) -> str:
    return args.email.strip().lower()


class _Invalid(Exception):
    """A surfaced bad-input/state condition: its payload is printed and the CLI exits 2."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload


def _require_token(email: str, hint: str = "run `onboard verify` first") -> str:
    token = state.token_for(email)
    if not token:
        raise _Invalid({"error": f"not verified — {hint}"})
    return token


# --- auth -------------------------------------------------------------------


def _cmd_verify_send(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    email = _email(args)
    # Public onboarding (issue #79): record the invitee's pending intent, attributed
    # to our referral code, then send their OTP. The account is created when they
    # verify (below). Self-hosted boxes can onboard too, no server-identity gate.
    code = (args.referral.strip() if getattr(args, "referral", None) else None) or cfg.referral_code
    resp = client.create_account(email, code)
    if "error" in resp:
        raise _Invalid(resp)  # e.g. a malformed email
    client.send_otp(email)
    _print({"sent": True, "email": email, "code_applied": bool(resp.get("code_applied"))})
    return 0


def _cmd_verify(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    email = _email(args)
    # Verifying the OTP is what actually CREATES the invitee's account (issue #79:
    # creation is deferred from verify-send to here) and returns their session token.
    token = client.verify_otp(email, args.code.strip())
    if not token:
        raise _Invalid({"error": "wrong or expired code — ask them to re-read it (or resend)"})
    state.update(email, token=token)
    _print({"verified": True, "email": email})
    return 0


# --- checkout + status ------------------------------------------------------


def _cmd_checkout(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    email = _email(args)
    token = _require_token(email, "run `onboard verify` with the buyer's code first")

    price: float | None = None
    if args.price is not None:
        if args.price < PLAN_FLOOR_USD:
            raise _Invalid({"error": f"price ${args.price:g} is below the ${PLAN_FLOOR_USD} floor", "floor_usd": PLAN_FLOOR_USD})
        price = args.price

    result = client.checkout(
        token=token,
        plan=PLAN,
        price=price,
        code=(args.code.strip() if args.code else None),
    )
    if "url" in result:
        # Stash the assigned subdomain + server id (both returned by checkout) so
        # later steps don't re-derive them; server_id is internal, so pop it out of
        # the agent-facing output.
        subdomain = result["subdomain"] if "subdomain" in result else None
        state.update(email, subdomain=subdomain, server_id=result.pop("server_id", None))
    _print(result)
    return 0 if "url" in result else 2


def _cmd_status(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    email = _email(args)
    token = _require_token(email)
    me = client.me(token)
    server = me["server"] if "server" in me else None
    if not server:
        _print({"status": "no_server", "hint": "run `onboard checkout` and have them pay"})
        return 0
    subdomain = server["subdomain"] if "subdomain" in server else None
    state.update(email, subdomain=subdomain, server_id=server["id"] if "id" in server else None)
    _print(
        {
            "status": server["status"] if "status" in server else None,
            "subdomain": subdomain,
            "url": server["url"] if "url" in server else None,
        }
    )
    return 0


# --- agent + Claude ---------------------------------------------------------


def _active_server(client: Client, token: str) -> dict[str, Any] | None:
    """The buyer's server iff it is live (`active`), else None."""
    me = client.me(token)
    server = me["server"] if "server" in me else None
    if server and "status" in server and server["status"] == "active":
        return server
    return None


def _require_active_server(client: Client, token: str) -> dict[str, Any]:
    server = _active_server(client, token)
    if not server:
        raise _Invalid({"error": "server not ready yet — poll `onboard status` until it is active"})
    return server


def _cmd_create_agent(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    email = _email(args)
    token = _require_token(email)
    server = _require_active_server(client, token)

    name = args.name.strip()
    context = args.context.strip() if args.context else None
    personality = args.personality.strip().lower() if args.personality else None
    server_token = client.server_token(token, server["id"])
    result = client.create_agent(subdomain=server["subdomain"], server_token=server_token, name=name)
    if "error" in result:
        raise _Invalid(result)
    # vestad normalizes the name (lowercases/strips); store what it ACTUALLY created
    # so claude-finish addresses /agents/<name>/provider with a name that validates.
    # Personality + seed context are stashed here and delivered through claude-finish's
    # set_provider, since the agent owns its config store (no env/create-time delivery).
    created_name = result["name"] if "name" in result else name
    state.update(email, agent_name=created_name, personality=personality, seed_context=context)
    _print({"created": True, "name": created_name})
    return 0


def _cmd_claude_start(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    email = _email(args)
    token = _require_token(email)
    server = _require_active_server(client, token)

    server_token = client.server_token(token, server["id"])
    result = client.claude_oauth_start(subdomain=server["subdomain"], server_token=server_token)
    if "error" in result:
        raise _Invalid(result)
    state.update(email, claude_session_id=result["session_id"])
    _print({"auth_url": result["auth_url"], "next": "have them open it, approve, and read the code back"})
    return 0


def _cmd_claude_finish(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    email = _email(args)
    token = _require_token(email)
    st = state.load(email)
    session_id = st["claude_session_id"] if "claude_session_id" in st else None
    if not session_id:
        raise _Invalid({"error": "no Claude auth in progress — run `onboard claude-start` first"})
    name = args.name.strip() if args.name else (st["agent_name"] if "agent_name" in st else None)
    if not name:
        raise _Invalid({"error": "unknown agent name — pass --name (the one used in create-agent)"})
    server = _require_active_server(client, token)

    server_token = client.server_token(token, server["id"])
    credentials = client.claude_oauth_complete(
        subdomain=server["subdomain"],
        server_token=server_token,
        session_id=session_id,
        code=args.code.strip(),
    )
    # The OAuth session is single-use and now consumed on the VM; forget it so a
    # retry can't re-post a spent session_id (which vestad rejects). If the attach
    # below fails the buyer must restart with claude-start.
    state.forget(email, "claude_session_id")
    result = client.set_provider(
        subdomain=server["subdomain"],
        server_token=server_token,
        name=name,
        credentials=credentials,
        model=(args.model or client.fetch_agent_defaults()["model"]),
        personality=st["personality"] if "personality" in st else None,
        seed_context=st["seed_context"] if "seed_context" in st else None,
    )
    if "error" in result:
        raise _Invalid(
            {"error": f"authorized on Anthropic's side but attaching it failed ({result['error']}); run `onboard claude-start` again to retry"}
        )
    # Onboarding complete — forget the buyer's session token.
    state.clear(email)
    _print({"connected": True, "name": name})
    return 0


# --- reference data ---------------------------------------------------------


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
                return sorted(s["name"] for s in data if "name" in s and s["name"])
        except (OSError, ValueError):
            continue
    return []


def _cmd_presets(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    # Read the live reference data from this box's vestad (the one source of truth) rather
    # than keeping hardcoded copies; skills still come from the on-box index.
    defaults = client.fetch_agent_defaults()
    _print(
        {
            "personalities": [p["name"] for p in client.fetch_personalities()],
            "skills": _installable_skills(),
            "plan_floor_usd": PLAN_FLOOR_USD,
            "claude_models": [m["id"] for m in client.fetch_claude_models()],
            "default_personality": defaults["personality"],
            "default_model": defaults["model"],
        }
    )
    return 0


def _cmd_links(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    _print(LINKS)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="onboard",
        description="Walk a stranger into Vesta: verify, checkout, create + connect their agent.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_send = sub.add_parser("verify-send", help="Email the buyer a 6-digit sign-in code.")
    p_send.add_argument("--email", required=True, help="The buyer's email.")
    p_send.add_argument("--referral", help="Override the referral code (defaults to $VESTA_CLOUD_REFERRAL_CODE).")

    p_verify = sub.add_parser("verify", help="Verify the code the buyer reads back.")
    p_verify.add_argument("--email", required=True)
    p_verify.add_argument("--code", required=True, help="The 6-digit code from their inbox.")

    p_checkout = sub.add_parser("checkout", help="Reserve + mint a Stripe link (auto subdomain).")
    p_checkout.add_argument("--email", required=True)
    p_checkout.add_argument("--price", type=float, help="Negotiated MONTHLY USD (>= the $24 floor; uncapped above).")
    p_checkout.add_argument("--code", help="Optional discount code to redeem at checkout.")

    p_status = sub.add_parser("status", help="Has the buyer paid + the VM come up?")
    p_status.add_argument("--email", required=True)

    p_agent = sub.add_parser("create-agent", help="Create the buyer's first agent.")
    p_agent.add_argument("--email", required=True)
    p_agent.add_argument("--name", required=True, help="What they want their vesta called.")
    p_agent.add_argument("--personality", help="Personality preset (see `onboard presets`).")
    p_agent.add_argument(
        "--context", help="Freeform setup notes for the new agent (what you learned about the user, skills/services to set up)."
    )

    p_cstart = sub.add_parser("claude-start", help="Begin connecting the buyer's Claude -> an auth link.")
    p_cstart.add_argument("--email", required=True)

    p_cfinish = sub.add_parser("claude-finish", help="Finish Claude connect with the pasted code.")
    p_cfinish.add_argument("--email", required=True)
    p_cfinish.add_argument("--code", required=True, help="The code the buyer pasted from the auth page.")
    p_cfinish.add_argument("--name", help="Agent name (defaults to the one from create-agent).")
    p_cfinish.add_argument("--model", help="Claude model (defaults to the box's configured default).")

    sub.add_parser("presets", help="Personality presets + installable skills + models.")
    sub.add_parser("links", help="Marketing + desktop/mobile install URLs.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    cfg = Config.load()
    client = Client(cfg)

    handlers = {
        "verify-send": _cmd_verify_send,
        "verify": _cmd_verify,
        "checkout": _cmd_checkout,
        "status": _cmd_status,
        "create-agent": _cmd_create_agent,
        "claude-start": _cmd_claude_start,
        "claude-finish": _cmd_claude_finish,
        "presets": _cmd_presets,
        "links": _cmd_links,
    }
    handler = handlers[args.command]
    try:
        return handler(args, client, cfg)
    except _Invalid as e:
        _print(e.payload)
        return 2
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
