"""The `browser` command: a thin client. Task 11 adds every RPC verb; this stage carries the daemon verbs only."""

from __future__ import annotations

import os
import pathlib as pl
import sys

from . import daemon, serve
from .runtime_paths import load_paths


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    paths = load_paths(os.environ, pl.Path.home())
    if not args or args[0] in ("-h", "--help", "help"):
        print(daemon.USAGE)
        return 0
    if args[0] == "daemon":
        return daemon.daemon_cmd(args[1] if len(args) > 1 else "", paths)
    if args[0] == "serve":
        return serve.main()
    print(daemon.USAGE, file=sys.stderr)
    return 1
