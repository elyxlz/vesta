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
from .config import DEFAULT_MODEL, LINKS, PERSONALITY_PRESETS, PLAN, PLAN_FLOOR_USD, Config


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _email(args: argparse.Namespace) -> str:
    return args.email.strip().lower()


# --- auth -------------------------------------------------------------------


def _cmd_verify_send(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    email = _email(args)
    client.send_otp(email)
    _print({"sent": True, "email": email})
    return 0


def _cmd_verify(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    email = _email(args)
    token = client.verify_otp(email, args.code.strip())
    if not token:
        _print({"error": "wrong or expired code — ask them to re-read it (or resend)"})
        return 2
    state.update(email, token=token)
    _print({"verified": True, "email": email})
    return 0


# --- checkout + status ------------------------------------------------------


def _cmd_checkout(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    email = _email(args)
    token = state.token_for(email)
    if not token:
        _print({"error": "not verified — run `onboard verify` with the buyer's code first"})
        return 2

    price: float | None = None
    if args.price is not None:
        if args.price < PLAN_FLOOR_USD:
            _print({"error": f"price ${args.price:g} is below the ${PLAN_FLOOR_USD} floor", "floor_usd": PLAN_FLOOR_USD})
            return 2
        price = args.price

    result = client.checkout(
        token=token,
        plan=PLAN,
        referral_code=args.referral or cfg.referral_code,
        price=price,
        code=(args.code.strip() if args.code else None),
    )
    if "url" in result:
        # Stash the assigned subdomain + server id (both returned by checkout) so
        # later steps don't re-derive them; server_id is internal, so pop it out of
        # the agent-facing output.
        state.update(email, subdomain=result.get("subdomain"), server_id=result.pop("server_id", None))
    _print(result)
    return 0 if "url" in result else 2


def _cmd_status(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    email = _email(args)
    token = state.token_for(email)
    if not token:
        _print({"error": "not verified — run `onboard verify` first"})
        return 2
    server = client.me(token).get("server")
    if not server:
        _print({"status": "no_server", "hint": "run `onboard checkout` and have them pay"})
        return 0
    state.update(email, subdomain=server.get("subdomain"), server_id=server.get("id"))
    _print({"status": server.get("status"), "subdomain": server.get("subdomain"), "url": server.get("url")})
    return 0


# --- agent + Claude ---------------------------------------------------------


def _active_server(client: Client, token: str) -> dict[str, Any] | None:
    """The buyer's server iff it is live (`active`), else None."""
    server = client.me(token).get("server")
    if server and server.get("status") == "active":
        return server
    return None


def _cmd_create_agent(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    email = _email(args)
    token = state.token_for(email)
    if not token:
        _print({"error": "not verified — run `onboard verify` first"})
        return 2
    server = _active_server(client, token)
    if not server:
        _print({"error": "server not ready yet — poll `onboard status` until it is active"})
        return 2

    name = args.name.strip()
    skills = [s.strip() for s in args.skills.split(",") if s.strip()] if args.skills else None
    server_token = client.server_token(token, server["id"])
    result = client.create_agent(
        subdomain=server["subdomain"],
        server_token=server_token,
        name=name,
        personality=(args.personality.strip().lower() if args.personality else None),
        skills=skills,
    )
    if "error" in result:
        _print(result)
        return 2
    # vestad normalizes the name (lowercases/strips); store what it ACTUALLY created
    # so claude-finish addresses /agents/<name>/provider with a name that validates.
    created_name = result.get("name", name)
    state.update(email, agent_name=created_name)
    _print({"created": True, "name": created_name})
    return 0


def _cmd_claude_start(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    email = _email(args)
    token = state.token_for(email)
    if not token:
        _print({"error": "not verified — run `onboard verify` first"})
        return 2
    server = _active_server(client, token)
    if not server:
        _print({"error": "server not ready yet — poll `onboard status` until it is active"})
        return 2

    server_token = client.server_token(token, server["id"])
    result = client.claude_oauth_start(subdomain=server["subdomain"], server_token=server_token)
    if "error" in result:
        _print(result)
        return 2
    state.update(email, claude_session_id=result["session_id"])
    _print({"auth_url": result["auth_url"], "next": "have them open it, approve, and read the code back"})
    return 0


def _cmd_claude_finish(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    email = _email(args)
    token = state.token_for(email)
    if not token:
        _print({"error": "not verified — run `onboard verify` first"})
        return 2
    st = state.load(email)
    session_id = st.get("claude_session_id")
    if not session_id:
        _print({"error": "no Claude auth in progress — run `onboard claude-start` first"})
        return 2
    name = args.name.strip() if args.name else st.get("agent_name")
    if not name:
        _print({"error": "unknown agent name — pass --name (the one used in create-agent)"})
        return 2
    server = _active_server(client, token)
    if not server:
        _print({"error": "server not ready yet — poll `onboard status` until it is active"})
        return 2

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
        model=(args.model or DEFAULT_MODEL),
    )
    if "error" in result:
        _print(
            {"error": f"authorized on Anthropic's side but attaching it failed ({result['error']}); run `onboard claude-start` again to retry"}
        )
        return 2
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
                return sorted(s.get("name", "") for s in data if s.get("name"))
        except (OSError, ValueError):
            continue
    return []


def _cmd_presets(args: argparse.Namespace, client: Client, cfg: Config) -> int:
    _print(
        {
            "personalities": list(PERSONALITY_PRESETS),
            "skills": _installable_skills(),
            "plan_floor_usd": PLAN_FLOOR_USD,
            "claude_models": ["opus", "sonnet", "haiku"],
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

    p_verify = sub.add_parser("verify", help="Verify the code the buyer reads back.")
    p_verify.add_argument("--email", required=True)
    p_verify.add_argument("--code", required=True, help="The 6-digit code from their inbox.")

    p_checkout = sub.add_parser("checkout", help="Reserve + mint a Stripe link (auto subdomain).")
    p_checkout.add_argument("--email", required=True)
    p_checkout.add_argument("--price", type=float, help="Negotiated MONTHLY USD (>= the $24 floor; uncapped above).")
    p_checkout.add_argument("--code", help="Optional discount code to redeem at checkout.")
    p_checkout.add_argument("--referral", help="Override the referral code (defaults to $VESTA_REFERRAL_CODE).")

    p_status = sub.add_parser("status", help="Has the buyer paid + the VM come up?")
    p_status.add_argument("--email", required=True)

    p_agent = sub.add_parser("create-agent", help="Create the buyer's first agent.")
    p_agent.add_argument("--email", required=True)
    p_agent.add_argument("--name", required=True, help="What they want their vesta called.")
    p_agent.add_argument("--personality", help="Personality preset (see `onboard presets`).")
    p_agent.add_argument("--skills", help="Comma-separated starting skills.")

    p_cstart = sub.add_parser("claude-start", help="Begin connecting the buyer's Claude -> an auth link.")
    p_cstart.add_argument("--email", required=True)

    p_cfinish = sub.add_parser("claude-finish", help="Finish Claude connect with the pasted code.")
    p_cfinish.add_argument("--email", required=True)
    p_cfinish.add_argument("--code", required=True, help="The code the buyer pasted from the auth page.")
    p_cfinish.add_argument("--name", help="Agent name (defaults to the one from create-agent).")
    p_cfinish.add_argument("--model", help=f"Claude model (default {DEFAULT_MODEL}).")

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
