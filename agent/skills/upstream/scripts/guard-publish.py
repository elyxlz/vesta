#!/usr/bin/env python3
"""Refuse to publish the owner's identity to a public repo.

Every instance files upstream work on behalf of one identifiable private person, and the gate for
that is prose in a SKILL.md. Prose is read at the moment you are pleased with the sentence you just
wrote, which is the moment the concrete example gets typed: the concrete case is always the
persuasive one.

So the gate also lives here, in the one place that runs whether or not anything remembers it: a
PreToolUse hook. It inspects Bash calls that reach a public code-hosting API and, when the command
or a file that command reads carries an identifier, denies the call and names the KIND of
identifier found.

Design rules, in order of importance:

- Fail OPEN on any internal error. A bug here must never block ordinary work.
- Fail CLOSED only on a positive identifier match in a publishing call. That is the whole point.
- Never print the matched value where it could be re-captured; print the identifier's KIND.
- Read-only calls are not publishing. Only bodies going out are checked.

Registered as a PreToolUse hook in ~/.claude/settings.json, with the hook payload on stdin.
Nothing registers it for you, and until something does it inspects nothing.

Exit 0 allows, exit 2 denies with the reason on stderr.
"""

import json
import os
import pathlib
import re
import sys
from datetime import UTC, datetime

PUBLIC_HOSTS = ("api.github.com", "github.com", "gitlab.com", "api.gitlab.com")
# Only verbs that send a body. A GET against the same host is reading, not publishing.
SENDING = ("POST", "PATCH", "PUT", '"POST"', "'POST'", '"PATCH"', "'PATCH'", "method=", "-d ", "--data")

PHONE = re.compile(r"\+[0-9]{9,15}")
JID = re.compile(r"[0-9]{10,15}@(?:s\.whatsapp\.net|lid|c\.us)")
EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Common English and ordinary technical prose. A name matching one of these would deny half of all
# legitimate calls, so they never count as identifiers. "unknown" is the identity placeholder a box
# carries until it learns whose it is.
STOPWORDS = {
    "goes",
    "by",
    "the",
    "and",
    "his",
    "her",
    "their",
    "name",
    "user",
    "agent",
    "test",
    "main",
    "dev",
    "app",
    "core",
    "data",
    "api",
    "web",
    "cli",
    "job",
    "run",
    "new",
    "old",
    "one",
    "two",
    "unknown",
}

MAX_BODY_BYTES = 2_000_000


def agent_dir():
    return pathlib.Path(os.environ["AGENT_DIR"] if "AGENT_DIR" in os.environ else "~/agent").expanduser()


def owner_names():
    """Names to refuse to publish: the owner's, plus everyone in their contacts.

    Resolved from this instance's own environment at call time. A list committed to the repo would
    publish the very names it exists to keep private."""
    names = set()
    home = pathlib.Path.home()
    env = os.environ["VESTA_OWNER"] if "VESTA_OWNER" in os.environ else ""
    if env:
        names.add(env)
    memory = agent_dir() / "MEMORY.md"
    if memory.is_file():
        for line in memory.read_text(errors="ignore").splitlines():
            m = re.match(r"-\s*\*\*Name\*\*:\s*(.+)", line)
            if m:
                names.add(m.group(1))
                break
    contacts = home / ".contacts"
    if contacts.is_dir():
        for f in contacts.glob("*.md"):
            names.add(f.stem)
            head = f.read_text(errors="ignore").split("\n", 1)[0]
            if head.startswith("# "):
                names.add(head[2:])
    out = set()
    for raw in names:
        for part in re.split(r"[,\-\s]+", raw.replace("*", "")):
            p = part.strip().lower()
            if len(p) > 2 and p not in STOPWORDS and p.isalpha():
                out.add(p)
    return out


def message_bodies(command):
    """Text of every path in the command that could be a message body.

    Binaries are skipped on a NUL byte. An interpreter or a helper on the command line is a path
    like any other, and decoding one as text yields byte sequences that match the address pattern,
    which would deny the call over the shebang rather than over anything being published."""
    found = []
    for path in re.findall(r"[\"']?(/[\w./-]+)[\"']?", command):
        p = pathlib.Path(path)
        try:
            if not p.is_file() or p.stat().st_size >= MAX_BODY_BYTES:
                continue
            raw = p.read_bytes()
            if b"\x00" in raw:
                continue
            found.append((str(p), raw.decode("utf-8", "ignore")))
        except OSError:
            continue
    return found


def hits(text, names):
    """The KINDS of identifier present in text. Never the values: this string is printed."""
    found = []
    low = text.lower()
    for n in names:
        if re.search(rf"\b{re.escape(n)}\b", low):
            found.append("a name")
            break
    if PHONE.search(text):
        found.append("a phone number")
    if JID.search(text):
        found.append("a whatsapp jid")
    for m in EMAIL.finditer(text):
        # noreply and example addresses are boilerplate, not the owner.
        if not m.group(0).lower().startswith(("noreply", "no-reply", "example")):
            found.append("an email address")
            break
    return found


def heartbeat(payload):
    """Stamp the time of this invocation, so a caller can tell registration from invocation.

    A hook nothing calls is indistinguishable from a hook that never had to fire, and both read as
    safety. A stamp refreshed on every invocation makes the difference observable. Overwrite,
    never append, so it cannot grow. Fail open like everything else here.

    Only a payload carrying harness-only fields counts. Running this file by hand exercises the
    LOGIC and says nothing about whether anything invokes it, and a hand test that stamped the
    file would launder itself into evidence of live firing.
    """
    if not any(key in payload for key in ("session_id", "hook_event_name", "transcript_path")):
        return
    try:
        stamp = agent_dir() / "data" / "guard-publish.fired"
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")
    except Exception:
        return


def publishing_command(payload):
    """The Bash command this call is about to run, when that command publishes to a public host.

    Empty for everything else, which is the common case and the one that must stay cheap."""
    if ("tool_name" not in payload) or payload["tool_name"] != "Bash":
        return ""
    tool_input = payload["tool_input"] if "tool_input" in payload else {}
    command = tool_input["command"] if "command" in tool_input else ""
    if not any(h in command for h in PUBLIC_HOSTS):
        return ""
    if not any(s in command for s in SENDING):
        return ""
    return command


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    heartbeat(payload)
    command = publishing_command(payload)
    if not command:
        return 0

    try:
        names = owner_names()
        for where, text in [("the command itself", command), *message_bodies(command)]:
            found = hits(text, names)
            if found:
                print(
                    "DENIED: this call publishes to a public repo and "
                    f"{where} carries {', '.join(sorted(set(found)))}.\n"
                    "The owner must not be identifiable upstream. Genericize it, then re-run.\n"
                    "Check what you are about to send with: "
                    "~/agent/skills/upstream/scripts/scrub-check.sh <file>",
                    file=sys.stderr,
                )
                return 2
    except Exception:
        # Fail open: a bug in this guard must not block ordinary work.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
