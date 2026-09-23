#!/usr/bin/env bash
# MEMORY.md budget, plus WHERE it grew since the last dream checkpoint.
#
# A flat character count says "over budget" but not where, so a hand-trim shaves every
# section blindly and the file regrows. The sections that actually grew since the last
# checkpoint are a short list; this prints it, so the cut lands where the growth is.
set -uo pipefail
file="$HOME/agent/MEMORY.md"
# The cap is a character budget: -m counts characters, and bare `wc -m` counts bytes under C.
chars=$(LC_ALL=C.UTF-8 wc -m < "$file")
limit=50000
pct=$((chars * 100 / limit))
target=$((limit * 85 / 100))
echo "${chars}/${limit} chars (${pct}%)"
if [ "$chars" -gt "$target" ]; then
    echo "OVER the 85% working target by $((chars - target)) chars. Trim to <= ${target}."
fi

sha="$(git -C "$HOME" log -n1 --format=%H --grep '^dream: nightly checkpoint' 2>/dev/null)"
if [ -z "$sha" ]; then
    echo "no prior dream checkpoint, so no growth attribution this run"
    exit 0
fi

prev="$(mktemp)"; trap 'rm -f "$prev"' EXIT
if ! git -C "$HOME" show "$sha:agent/MEMORY.md" > "$prev" 2>/dev/null; then
    echo "checkpoint $sha holds no agent/MEMORY.md; no growth attribution"
    exit 0
fi

echo
echo "GROWTH BY SECTION since checkpoint ${sha:0:8}. Cut where it grew, not everywhere:"
python3 - "$prev" "$file" <<'PY'
import sys, re
def sections(path):
    out, name, buf = {}, "(preamble)", []
    for line in open(path, encoding="utf-8", errors="replace"):
        if re.match(r"^#{1,3} ", line):
            out[name] = out.get(name, 0) + sum(len(x) for x in buf)
            name, buf = line.strip()[:58], []
        else:
            buf.append(line)
    out[name] = out.get(name, 0) + sum(len(x) for x in buf)
    return out
a, b = sections(sys.argv[1]), sections(sys.argv[2])
rows = []
for k in set(a) | set(b):
    d = b.get(k, 0) - a.get(k, 0)
    if d:
        rows.append((d, k, a.get(k, 0), b.get(k, 0)))
rows.sort(reverse=True)
if not rows:
    print("  no section changed size")
for d, k, old, new in rows[:12]:
    sign = "+" if d > 0 else ""
    print(f"  {sign}{d:>7}  {new:>6} now ({old} before)  {k}")
grown = sum(d for d, *_ in rows if d > 0)
shrunk = -sum(d for d, *_ in rows if d < 0)
print(f"\n  added {grown} chars, removed {shrunk}, net {grown - shrunk:+}")
print("  NOTE: User State and the Self State line are rewritten nightly by design;")
print("  judge them on size, not on the fact that they changed.")
PY
