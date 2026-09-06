"""The `browser` command: one JSON request over the daemon socket, one JSON line back.

Every browser decision lives in the daemon. This client parses arguments, reads the program from
stdin, sends one request, and prints one line: stdout on success, stderr on failure, exit 1.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib as pl
import signal
import sys
import threading
import uuid

from . import daemon
from . import protocol as p
from .client import send
from .runtime_paths import Paths, load_paths

USAGE = """Usage:
  browser exec --session <name> [--stealth] [--timeout <secs>]   # Python on stdin
  browser daemon start|stop|restart|status
  browser doctor | engines | sessions | session stop <name> | stop-all
  browser handover start [--url <url>] [--session <name>] [--stealth] [--minutes <n>]
  browser handover status | stop"""
# Past the daemon's own deadlines, so a slow answer arrives instead of reading as a dead daemon.
RPC_TIMEOUT_SLACK_SECS = 30
# Past the daemon's own bring-up budget, so a slow handover answers instead of reading as a dead
# daemon, and inside the 120s a Bash tool call allows by default.
HANDOVER_RPC_TIMEOUT_SECS = 110.0
# stop-all waits out a session start or a handover teardown before it stops them, so its answer
# waits the same way: past the daemon's own budgets, and inside the Bash tool's 120s.
STOP_ALL_TIMEOUT_SECS = HANDOVER_RPC_TIMEOUT_SECS
CANCEL_TIMEOUT_SECS = 5


def _request_id() -> str:
    return f"r_{uuid.uuid4().hex[:12]}"


def emit(result: p.Result) -> int:
    line = json.dumps(result)
    if result["ok"]:
        print(line)
        return 0
    print(line, file=sys.stderr)
    return 1


def _parser() -> argparse.ArgumentParser:
    # argparse prepends its own "usage: "; passing the full USAGE (which already opens with
    # "Usage:") would print "usage: Usage:" on an unknown command, so strip that header here.
    parser = argparse.ArgumentParser(prog="browser", usage=USAGE.removeprefix("Usage:\n").strip(), add_help=True)
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("exec")
    run.add_argument("--session", default=p.DEFAULT_SESSION)
    run.add_argument("--stealth", action="store_true")
    run.add_argument("--timeout", type=int, default=p.EXEC_TIMEOUT_DEFAULT_SECS)
    for name in ("doctor", "engines", "sessions", "stop-all"):
        sub.add_parser(name)
    session = sub.add_parser("session")
    session.add_argument("verb", choices=["stop"])
    session.add_argument("name")
    handover = sub.add_parser("handover")
    handover.add_argument("verb", choices=["start", "status", "stop"])
    handover.add_argument("--url", default=None)
    handover.add_argument("--session", default=p.DEFAULT_SESSION)
    handover.add_argument("--stealth", action="store_true")
    handover.add_argument("--minutes", type=int, default=None)
    return parser


def _exec(paths: Paths, args: argparse.Namespace) -> int:
    request_id = _request_id()
    payload = p.request(
        "exec",
        request_id,
        session=args.session,
        mode="stealth" if args.stealth else None,
        timeout_s=args.timeout,
        code=sys.stdin.read(),
    )
    cancelled = threading.Event()

    def on_signal(_signum: int, _frame: object) -> None:
        cancelled.set()
        send(paths, p.request("cancel", _request_id(), target_request_id=request_id), CANCEL_TIMEOUT_SECS)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    # The daemon answers inside its engine-start budget plus the program's clamped budget; the wait
    # here covers both, so an out-of-range --timeout still gets one envelope back.
    budget = p.SESSION_START_BUDGET_SECS + p.clamp_timeout(args.timeout) + RPC_TIMEOUT_SLACK_SECS
    result = send(paths, payload, budget)
    if cancelled.is_set():
        err = p.error("cancelled", "execution", "interrupted by the caller", retryable=False, suggested_action="rerun when ready")
        result = p.result(request_id=request_id, op="exec", ok=False, session=result["session"], err=err)
    return emit(result)


def _rpc(paths: Paths, op: p.Op, *, timeout: float = RPC_TIMEOUT_SLACK_SECS, **fields: p.JsonValue) -> int:
    return emit(send(paths, p.request(op, _request_id(), **fields), timeout))


def _handover(paths: Paths, args: argparse.Namespace) -> int:
    if args.verb == "start":
        return _rpc(
            paths,
            "handover_start",
            timeout=HANDOVER_RPC_TIMEOUT_SECS,
            url=args.url,
            session=args.session,
            mode="stealth" if args.stealth else None,
            minutes=args.minutes,
        )
    return _rpc(paths, "handover_status" if args.verb == "status" else "handover_stop", timeout=HANDOVER_RPC_TIMEOUT_SECS)


def _dispatch(paths: Paths, args: argparse.Namespace) -> int:
    if args.command == "exec":
        return _exec(paths, args)
    if args.command == "session":
        return _rpc(paths, "session_stop", session=args.name)
    if args.command == "handover":
        return _handover(paths, args)
    if args.command == "stop-all":
        return _rpc(paths, "stop_all", timeout=STOP_ALL_TIMEOUT_SECS)
    return _rpc(paths, args.command)


def main(argv: list[str] | None = None) -> int:
    args_list = sys.argv[1:] if argv is None else argv
    if not args_list or args_list[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    paths = load_paths(os.environ, pl.Path.home())
    if args_list[0] == "daemon":
        return daemon.daemon_cmd(args_list[1] if len(args_list) > 1 else "", paths)
    try:
        args = _parser().parse_args(args_list)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 1
    return _dispatch(paths, args)
