#!/usr/bin/env python3
"""Fast targeted membership check for leaked secrets in the event/DB stores.

Why this exists (companion to redact_secrets.py, not a replacement):
  redact_secrets.py is the heavy full-corpus scanner+scrubber. On the ~100MB
  events.db it does not finish inside the Bash tool's hard 120s foreground cap,
  so it always ends up backgrounded, and its backgrounded output covers only
  file-stores (no events verdict). That gap caused several "reported clean"
  misses. The reliable events verdict is a TARGETED MEMBERSHIP CHECK: take each
  known secret VALUE, substring-count it across every *.db, print NAME|count
  only. This script is exactly that, and it finishes in well under a second.

Safety contract:
  - Secret VALUES are read into memory and NEVER printed. Only NAME|count lines.
  - Names in ALLOWLIST are usernames/handles, not the secret class: reported for
    visibility but never cause a non-zero exit.
  - Exit 0 = every secret-class value has 0 hits (clean). Exit 1 = a real leak.

Usage:
  python3 scan_event_secrets.py            # scan ~/agent/data/*.db
  python3 scan_event_secrets.py --all      # also include pending-sends dbs
  python3 scan_event_secrets.py --min-len 8
"""

import argparse
import re
import sys
from pathlib import Path

# Var names that are NOT the secret class (usernames, handles). Reported, never fail.
ALLOWLIST = {"TRACKER_USERNAME", "SOCKS5_USER", "HUE_USERNAME", "QB_USERNAME"}

# Only these name patterns are treated as secret-bearing.
SECRET_PAT = re.compile(r"PASS|KEY|TOKEN|SECRET|PWD|CRED")

SOURCES = [Path("~/.bashrc").expanduser(), Path("/run/vestad-env")]


def load_secrets():
    """Return {name: value} from export lines. Values never leave this process
    except as substring counts."""
    secrets = {}
    for path in SOURCES:
        try:
            with path.open() as f:
                for line in f:
                    m = re.match(r"\s*export\s+([A-Z0-9_]+)=(.*)", line)
                    if not m:
                        continue
                    name, val = m.group(1), m.group(2).strip()
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                        val = val[1:-1]
                    secrets[name] = val
        except FileNotFoundError:
            continue
    return secrets


def db_paths(include_all):
    data = Path("~/agent/data").expanduser()
    paths = list(data.glob("events.db"))
    paths += list(data.glob("*.db"))
    if include_all:
        paths += list(Path("~/.email-client").expanduser().glob("pending-sends.db"))
        paths += list(Path("~/.microsoft").expanduser().glob("pending-sends.db"))
    # de-dup, keep only real files
    return sorted({p for p in paths if p.is_file()})


def main():
    ap = argparse.ArgumentParser(description="Targeted secret membership check across DB stores.")
    ap.add_argument("--all", action="store_true", help="also scan pending-sends dbs")
    ap.add_argument("--min-len", type=int, default=6, help="skip values shorter than this")
    args = ap.parse_args()

    secrets = load_secrets()
    blob = b""
    scanned = db_paths(args.all)
    for p in scanned:
        with p.open("rb") as f:
            blob += f.read()

    print(f"# scanned {len(scanned)} db file(s)")
    leaked = 0
    for name in sorted(secrets):
        if not SECRET_PAT.search(name) and name not in ALLOWLIST:
            continue
        val = secrets[name]
        if not val or len(val) < args.min_len:
            print(f"{name}|(too short to scan)")
            continue
        cnt = blob.count(val.encode("utf-8", "ignore"))
        tag = " ALLOWLIST" if name in ALLOWLIST else ""
        print(f"{name}|{cnt}{tag}")
        if cnt > 0 and name not in ALLOWLIST:
            leaked += 1

    if leaked:
        print(f"# LEAK: {leaked} secret-class value(s) present in DB stores -> scrub with redact_secrets.py --scrub", file=sys.stderr)
        return 1
    print("# clean: no secret-class values found in DB stores")
    return 0


if __name__ == "__main__":
    sys.exit(main())
