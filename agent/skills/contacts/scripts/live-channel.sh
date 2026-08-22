#!/usr/bin/env bash
# live-channel.sh -- which channel is a contact ACTUALLY reading?
#
# Answers one question per contact: when did this person last send YOU something, per channel.
# Never your own outbound. Reading your own sends as "where the conversation is" is how a message
# goes to a channel the person left, after which their silence gets recorded as an answer.
#
# Usage: live-channel.sh [contact_name]     (default: every contact with inbound)
#        live-channel.sh --silence-hours    (whole hours since the OWNER last wrote, or UNMEASURED)
#
# --silence-hours prints ONE token: an integer, or the literal UNMEASURED with exit 2. It never
# prints a number it did not measure. A caller that rations on silence must treat any non-integer
# as "cannot tell" and ration as if the silence were long, because an unreadable store and a
# talkative user are the same output otherwise, and that is the direction that fails silently.

set -uo pipefail

CONTACT="${1:-}"
EVENTS="${VESTA_EVENTS_DB:-$HOME/agent/data/events.db}"

if [ ! -f "$EVENTS" ]; then
    if [ "$CONTACT" = "--silence-hours" ]; then echo UNMEASURED; exit 2; fi
    echo "UNMEASURED: $EVENTS not found, so channel liveness was NOT determined." >&2
    exit 2
fi

# Never guesses the owner's name: no structured source for it exists (see SKILL.md). app-chat is
# their own screen, so inbound there is theirs by construction and needs no name; VESTA_OWNER folds
# in named channels. The fallback can only over-report silence, never under-report it.
OWNER="${VESTA_OWNER:-}"

if [ "$CONTACT" = "--silence-hours" ]; then
    VESTA_OWNER="$OWNER" python3 - "$EVENTS" <<'PY'
import sqlite3, sys, re, os, json, datetime

def sender(data):
    """The person who sent it, from the event's own normalized `sender` field.

    core writes this via notif_sender(), which searches contact_name, handle, from, author and
    sender_address and returns the first present, so one read covers every channel. Scraping the
    name out of `summary` instead only appears to work: summary is a per-source presentation string
    and a source that attaches `handle` rather than `contact_name` would be silently invisible.
    `fields` is not a fallback either, since notif_facet_fields excludes every identity field by
    construction. Empty means no person: app-chat (the owner's own screen) or a service.
    """
    try:
        return json.loads(data).get("sender") or ""
    except (ValueError, AttributeError):
        return ""


db = sys.argv[1]
owner = os.environ.get("VESTA_OWNER", "").strip().lower()
try:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = list(c.execute(
        "select ts, data from events where json_extract(data,'$.type')='notification'"))
except Exception:
    print("UNMEASURED"); sys.exit(2)

# Zero notification rows is an unwritten store, not a quiet user. Reporting a silence figure off an
# empty table would be inventing one.
if not rows:
    print("UNMEASURED"); sys.exit(2)

best = ""
for ts, data in rows:
    m = re.search(r'"source":\s*"([^"]*)"', data)
    src = m.group(1) if m else "?"
    if src in ("core", "tasks", "vestad"):
        continue                      # machine chatter, not a person
    if src == "app-chat":
        pass                          # the owner's own screen, theirs by construction
    elif owner:
        if owner not in sender(data).strip().lower():
            continue
    else:
        continue                      # no name to match on, so this channel cannot be attributed
    if ts > best:
        best = ts

if not best:
    print("UNMEASURED"); sys.exit(2)
try:
    t = datetime.datetime.fromisoformat(best.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)
except ValueError:
    print("UNMEASURED"); sys.exit(2)
delta = datetime.datetime.now(datetime.timezone.utc) - t
print(max(0, int(delta.total_seconds() // 3600)))
PY
    exit $?
fi

VESTA_OWNER="$OWNER" python3 - "$EVENTS" "$CONTACT" <<'PY'
import sqlite3, sys, re, os, json, collections

def sender(data):
    """The person who sent it, from the event's own normalized `sender` field.

    core writes this via notif_sender(), which searches contact_name, handle, from, author and
    sender_address and returns the first present, so one read covers every channel. Scraping the
    name out of `summary` instead only appears to work: summary is a per-source presentation string
    and a source that attaches `handle` rather than `contact_name` would be silently invisible.
    `fields` is not a fallback either, since notif_facet_fields excludes every identity field by
    construction. Empty means no person: app-chat (the owner's own screen) or a service.
    """
    try:
        return json.loads(data).get("sender") or ""
    except (ValueError, AttributeError):
        return ""


db, want = sys.argv[1], sys.argv[2].strip().lower()
owner = os.environ.get("VESTA_OWNER", "").strip()
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

rows = list(c.execute(
    "select ts, data from events where json_extract(data,'$.type')='notification'"))
if not rows:
    print("UNMEASURED: zero notification rows, so the store is not being written and an empty "
          "per-channel result below would mean nothing.", file=sys.stderr)
    sys.exit(2)

last, unattributed = {}, set()
for ts, data in rows:
    src = re.search(r'"source":\s*"([^"]*)"', data)
    src = src.group(1) if src else "?"
    if src in ("core", "tasks", "vestad"):
        continue
    name = sender(data)
    # app-chat carries no sender because it is the owner's own screen; folding it under their name
    # is what lets the two channels be compared at all. Anything else without one is a service, not
    # a person, and is dropped: an empty sender is a property of the event, whereas a denylist of
    # machine source names is box-specific and always one skill out of date.
    if name:
        pass
    elif src == "app-chat":
        name = owner or "(owner, app-chat)"
    else:
        unattributed.add(src)
        continue
    key = (name, src)
    if ts > last.get(key, ""):
        last[key] = ts

by_person = collections.defaultdict(dict)
for (name, src), ts in last.items():
    by_person[name][src] = ts

hit = False
for name in sorted(by_person):
    if want and want not in name.lower():
        continue
    hit = True
    chans = sorted(by_person[name].items(), key=lambda kv: kv[1], reverse=True)
    live = chans[0][0]
    print(f"{name}:")
    for src, ts in chans:
        mark = "  <-- LIVE, send here" if src == live else ""
        print(f"    {src:<10} last inbound {ts[:16].replace('T',' ')} UTC{mark}")

if unattributed and not want:
    print("\n  (dropped inbound with no sender from: "
          + ", ".join(sorted(unattributed)) + ". These are services, not people.)")

if want and not hit:
    print(f"no inbound from anyone matching '{want}'. That is not proof they are silent: check the "
          f"spelling against the list this prints when called with no argument.", file=sys.stderr)
    sys.exit(1)
PY
