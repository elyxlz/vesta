"""Bash-compatible CLI dispatcher.

Command surface matches the old TypeScript CLI so existing agent prompts keep working.
Also supports a `browser <<'PY' ... PY` stdin mode for multi-line scripts (helpers
are pre-imported).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import admin, helpers, snapshot


SESSION_ENV = "BROWSER_SESSION"


def _snapshot_banner(interactive_only: bool = False) -> str:
    """Take a snapshot and format it. Called after every mutating action."""
    try:
        snap = snapshot.snapshot(interactive_only=interactive_only, compact=False)
    except Exception as e:
        return f"(snapshot failed: {e})"
    header = f"# {snap['title'] or '(no title)'}\n# {snap['url']}\n# {snap['ref_count']} interactive refs"
    banner = helpers.recipe_banner(snap["url"])
    parts = [header]
    if banner:
        parts.append(banner)
    parts.append(snap["text"])
    return "\n\n".join(parts)


def _print_snapshot(interactive_only: bool = False) -> None:
    print(_snapshot_banner(interactive_only=interactive_only))


# ── Commands ──────────────────────────────────────────────────


def cmd_launch(args: argparse.Namespace) -> int:
    profile = Path(args.user_data_dir) if args.user_data_dir else None
    running = admin.launch_chrome(
        headless=args.headless,
        stealth=args.stealth,
        no_sandbox=args.no_sandbox,
        user_data_dir=profile,
        executable=args.executable,
        port=args.port,
    )
    admin.ensure_daemon()
    print(
        json.dumps(
            {
                "session": admin._session_name(),
                "cdp_port": running.cdp_port,
                "pid": running.pid,
                "user_data_dir": str(running.user_data_dir),
                "stealth": args.stealth,
                "headless": args.headless,
            },
            indent=2,
        )
    )
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    """Connect to an externally running Chrome via its /json/version URL."""
    import os
    import urllib.request

    with urllib.request.urlopen(f"{args.url.rstrip('/')}/json/version", timeout=5) as r:
        data = json.loads(r.read())
    ws = data.get("webSocketDebuggerUrl", "")
    if not ws:
        print(f"no webSocketDebuggerUrl at {args.url}/json/version", file=sys.stderr)
        return 1
    os.environ["VESTA_BROWSER_CDP_WS"] = ws
    admin.ensure_daemon()
    print(json.dumps({"session": admin._session_name(), "ws": ws}))
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    admin.shutdown()
    return 0


def cmd_stop_all(args: argparse.Namespace) -> int:
    admin.stop_all()
    return 0


def cmd_sessions(args: argparse.Namespace) -> int:
    print(json.dumps(admin.list_sessions(), indent=2))
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    tid = helpers.new_tab(args.url)
    helpers.wait_for_load()
    _print_snapshot()
    print(f"\n# target_id: {tid}")
    return 0


def cmd_navigate(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    helpers.goto(args.url)
    helpers.wait_for_load()
    _print_snapshot()
    return 0


def cmd_reload(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    helpers.reload()
    helpers.wait_for_load()
    _print_snapshot()
    return 0


def cmd_back(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    helpers.back()
    helpers.wait_for_load()
    _print_snapshot()
    return 0


def cmd_forward(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    helpers.forward()
    helpers.wait_for_load()
    _print_snapshot()
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    _print_snapshot(interactive_only=args.interactive)
    return 0


def cmd_screenshot(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    path = helpers.screenshot(path=args.path, full_page=args.full_page)
    print(path)
    return 0


def cmd_pdf(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    path = helpers.pdf(path=args.path)
    print(path)
    return 0


def cmd_click(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    if args.at:
        x, y = args.at
        helpers.click(x, y, button="right" if args.right else "left", clicks=2 if args.double else 1)
    else:
        if not args.ref:
            print("click needs a ref or --at X Y", file=sys.stderr)
            return 2
        helpers.click_ref(args.ref, button="right" if args.right else "left", clicks=2 if args.double else 1)
    helpers.wait(0.2)
    _print_snapshot()
    return 0


def cmd_type(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    helpers.type_ref(args.ref, args.text, submit=args.submit, slowly=args.slowly)
    helpers.wait(0.2)
    _print_snapshot()
    return 0


def cmd_press(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    mods = [m.capitalize() for m in (args.modifiers or [])]
    if "+" in args.key and not args.modifiers:
        # Accept "Control+a" shorthand.
        pieces = args.key.split("+")
        mods = [p.capitalize() for p in pieces[:-1]]
        args.key = pieces[-1]
    helpers.press_key(args.key, modifiers=mods or 0)
    helpers.wait(0.2)
    _print_snapshot()
    return 0


def cmd_hover(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    helpers.hover_ref(args.ref)
    return 0


def cmd_scroll(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    if args.down is not None:
        helpers.scroll(100, 300, dy=args.down)
    elif args.up is not None:
        helpers.scroll(100, 300, dy=-args.up)
    elif args.ref:
        info = snapshot.read_ref(helpers.current_tab()["target_id"], args.ref)
        helpers.cdp("DOM.scrollIntoViewIfNeeded", backendNodeId=info["backend_node_id"])
    return 0


def cmd_wait(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    if args.text:
        ok = helpers.wait_for_text(args.text, timeout=args.timeout)
    elif args.url:
        ok = helpers.wait_for_url(args.url, timeout=args.timeout)
    elif args.load_state == "networkidle" or args.load_state == "load":
        ok = helpers.wait_for_load(timeout=args.timeout)
    elif args.time is not None:
        helpers.wait(args.time / 1000.0)
        ok = True
    else:
        print("wait needs one of: --text, --url, --load-state, --time", file=sys.stderr)
        return 2
    print(json.dumps({"matched": ok}))
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    result = helpers.js(args.expression)
    print(json.dumps(result, default=str))
    return 0


def cmd_cdp(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    params = json.loads(args.params) if args.params else {}
    result = helpers.cdp(args.method, **params)
    print(json.dumps(result, default=str, indent=2))
    return 0


def cmd_http_get(args: argparse.Namespace) -> int:
    print(helpers.http_get(args.url))
    return 0


def cmd_tabs(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    print(json.dumps(helpers.list_tabs(), indent=2))
    return 0


def cmd_focus(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    helpers.switch_tab(args.target_id)
    _print_snapshot()
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    helpers.close_tab(args.target_id)
    return 0


def cmd_resize(args: argparse.Namespace) -> int:
    admin.ensure_daemon()
    helpers.cdp(
        "Emulation.setDeviceMetricsOverride",
        width=args.width,
        height=args.height,
        deviceScaleFactor=1,
        mobile=False,
    )
    return 0


def cmd_stdin(args: argparse.Namespace) -> int:
    """Run multi-line Python from stdin with helpers pre-imported, browser-harness style."""
    admin.ensure_daemon()
    if sys.stdin.isatty():
        print(
            "browser stdin mode reads from stdin. Use:\n"
            "  browser <<'PY'\n"
            "  print(page_info())\n"
            "  PY",
            file=sys.stderr,
        )
        return 2
    code = sys.stdin.read()
    exec_globals = {name: getattr(helpers, name) for name in dir(helpers) if not name.startswith("_")}
    exec_globals["snapshot"] = snapshot.snapshot
    exec(code, exec_globals)
    return 0


# ── Argparse wiring ───────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="browser", description="Vesta browser CLI.")
    sub = p.add_subparsers(dest="cmd")

    # Session lifecycle
    lp = sub.add_parser("launch", help="Launch a Chromium for this session.")
    lp.add_argument("--headless", action="store_true")
    lp.add_argument("--stealth", action="store_true")
    lp.add_argument("--no-sandbox", action="store_true")
    lp.add_argument("--user-data-dir", default=None)
    lp.add_argument("--executable", default=None)
    lp.add_argument("--port", type=int, default=None)
    lp.set_defaults(func=cmd_launch)

    cp = sub.add_parser("connect", help="Connect to an externally running Chrome.")
    cp.add_argument("url", help="Base URL, e.g. http://localhost:9222")
    cp.set_defaults(func=cmd_connect)

    sub.add_parser("stop", help="Stop this session.").set_defaults(func=cmd_stop)
    sub.add_parser("stop-all", help="Stop all sessions.").set_defaults(func=cmd_stop_all)
    sub.add_parser("sessions", help="List active sessions.").set_defaults(func=cmd_sessions)

    # Navigation
    op = sub.add_parser("open", help="Open a URL in a new tab.")
    op.add_argument("url")
    op.set_defaults(func=cmd_open)

    np = sub.add_parser("navigate", help="Navigate current tab.")
    np.add_argument("url")
    np.set_defaults(func=cmd_navigate)

    sub.add_parser("reload").set_defaults(func=cmd_reload)
    sub.add_parser("back").set_defaults(func=cmd_back)
    sub.add_parser("forward").set_defaults(func=cmd_forward)

    # Reads
    sp = sub.add_parser("snapshot", help="Accessibility snapshot with refs.")
    sp.add_argument("--interactive", action="store_true")
    sp.set_defaults(func=cmd_snapshot)

    ssp = sub.add_parser("screenshot")
    ssp.add_argument("--path", default="/tmp/screenshot.png")
    ssp.add_argument("--full-page", action="store_true")
    ssp.set_defaults(func=cmd_screenshot)

    pp = sub.add_parser("pdf")
    pp.add_argument("--path", default="/tmp/page.pdf")
    pp.set_defaults(func=cmd_pdf)

    # Actions
    clp = sub.add_parser("click", help="Click a ref (e1) or --at X Y.")
    clp.add_argument("ref", nargs="?")
    clp.add_argument("--at", nargs=2, type=float, metavar=("X", "Y"))
    clp.add_argument("--double", action="store_true")
    clp.add_argument("--right", action="store_true")
    clp.set_defaults(func=cmd_click)

    tp = sub.add_parser("type", help="Type into a ref.")
    tp.add_argument("ref")
    tp.add_argument("text")
    tp.add_argument("--submit", action="store_true")
    tp.add_argument("--slowly", action="store_true")
    tp.set_defaults(func=cmd_type)

    prp = sub.add_parser("press")
    prp.add_argument("key")
    prp.add_argument("--modifiers", nargs="*")
    prp.set_defaults(func=cmd_press)

    hp = sub.add_parser("hover")
    hp.add_argument("ref")
    hp.set_defaults(func=cmd_hover)

    scp = sub.add_parser("scroll")
    scp.add_argument("ref", nargs="?")
    scp.add_argument("--up", type=int)
    scp.add_argument("--down", type=int)
    scp.set_defaults(func=cmd_scroll)

    wp = sub.add_parser("wait")
    wp.add_argument("--text")
    wp.add_argument("--url")
    wp.add_argument("--time", type=int, help="milliseconds")
    wp.add_argument("--load-state")
    wp.add_argument("--timeout", type=float, default=20.0)
    wp.set_defaults(func=cmd_wait)

    ep = sub.add_parser("evaluate", aliases=["js"])
    ep.add_argument("expression")
    ep.set_defaults(func=cmd_evaluate)

    cdp_p = sub.add_parser("cdp", help="Raw CDP escape hatch.")
    cdp_p.add_argument("method")
    cdp_p.add_argument("params", nargs="?", help='JSON params, e.g. \'{"url":"..."}\'.')
    cdp_p.set_defaults(func=cmd_cdp)

    hg = sub.add_parser("http-get", aliases=["fetch"])
    hg.add_argument("url")
    hg.set_defaults(func=cmd_http_get)

    sub.add_parser("tabs").set_defaults(func=cmd_tabs)

    fp = sub.add_parser("focus")
    fp.add_argument("target_id")
    fp.set_defaults(func=cmd_focus)

    xp = sub.add_parser("close")
    xp.add_argument("target_id")
    xp.set_defaults(func=cmd_close)

    rp = sub.add_parser("resize")
    rp.add_argument("width", type=int)
    rp.add_argument("height", type=int)
    rp.set_defaults(func=cmd_resize)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    # browser-harness style: if nothing on argv and stdin has content, run as Python script.
    if not argv and not sys.stdin.isatty():
        return cmd_stdin(argparse.Namespace())

    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
