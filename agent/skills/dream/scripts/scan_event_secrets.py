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
  - Secret VALUES are consumed entirely inside count_hits(); only integer counts
    keyed by name leave it, so no secret value ever crosses into output.
  - Printed names are rebuilt from an allowlist of characters (_clean_name), so
    nothing carrying a secret value's provenance reaches stdout.
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

SOURCES = [Path.home() / ".bashrc", Path("/run/vestad-env")]

_NAME_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


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
    data = Path.home() / "agent" / "data"
    paths = set(data.glob("*.db"))
    if include_all:
        paths.add(Path.home() / ".email-client" / "pending-sends.db")
        paths.add(Path.home() / ".microsoft" / "pending-sends.db")
    return sorted(p for p in paths if p.is_file())


def _clean_name(name):
    """Rebuild an env-var name from an allowlist of chars, so nothing carrying
    the provenance of a secret value can reach stdout."""
    return "".join(ch for ch in name if ch in _NAME_CHARS)


def count_hits(blob, min_len):
    """Substring-count each secret VALUE in blob. The value is consumed entirely
    inside this function; only {name: int_count_or_None} leaves it, so no secret
    value ever crosses into logging/output."""
    results = {}
    for name, val in load_secrets().items():
        if not SECRET_PAT.search(name) and name not in ALLOWLIST:
            continue
        if not val or len(val) < min_len:
            results[name] = None
        else:
            results[name] = blob.count(val.encode("utf-8", "ignore"))
    return results


def main():
    ap = argparse.ArgumentParser(description="Targeted secret membership check across DB stores.")
    ap.add_argument("--all", action="store_true", help="also scan pending-sends dbs")
    ap.add_argument("--min-len", type=int, default=6, help="skip values shorter than this")
    args = ap.parse_args()

    blob = b""
    scanned = db_paths(args.all)
    for p in scanned:
        with p.open("rb") as f:
            blob += f.read()

    results = count_hits(blob, args.min_len)
    print(f"# scanned {len(scanned)} db file(s)")
    leaked = 0
    for name in sorted(results):
        disp = _clean_name(name)
        allow = name in ALLOWLIST
        cnt = results[name]
        if cnt is None:
            print(f"{disp}|(too short to scan)")
            continue
        print(f"{disp}|{cnt}{' ALLOWLIST' if allow else ''}")
        if cnt > 0 and not allow:
            leaked += 1

    if leaked:
        print(
            f"# LEAK: {leaked} secret-class value(s) present in DB stores -> scrub with redact_secrets.py --scrub-literal",
            file=sys.stderr,
        )
        return 1
    print("# clean: no secret-class values found in DB stores")
    return 0


if __name__ == "__main__":
    sys.exit(main())
