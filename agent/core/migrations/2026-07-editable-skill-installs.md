Your skills reach the world through their command line tools, and each tool
should run from its **live source** under `~/agent`. When a tool is instead a
frozen, build-once copy, it keeps running the code it was built from, so fixes to
that skill (yours, or from upstream sync) silently never reach it. This is what
made the app-chat skill deliver every app message to you twice: a stale copy and
the live agent were both writing the notification.

Make each of your skill tools run from live source. You know which skills you
have and how you installed them, so use your judgment; the checks and fixes below
are safe to repeat.

### Python tools (`uv tool`)

These should be **editable** installs (linked to their source), not frozen copies.
List the frozen ones. This only reads, and it is also how you confirm success
later, a clean run prints nothing:

```bash
tools_dir=$(uv tool dir 2>/dev/null) || tools_dir="$HOME/.local/share/uv/tools"
for tool_dir in "$tools_dir"/*/; do
  meta=$(find "$tool_dir" -name direct_url.json 2>/dev/null | head -1)
  [ -z "$meta" ] && continue
  grep -q '"editable": *true' "$meta" && continue
  src=$(grep -o '"url": *"file://[^"]*"' "$meta" | head -1 | sed -E 's/.*"file:\/\/([^"]*)".*/\1/')
  [ -n "$src" ] && echo "frozen: $(basename "$tool_dir")  <- $src"
done
```

Reinstall each frozen one editable from the skill's **current** source directory.
That is usually the path shown; if the skill has moved, find where it lives now
(a built-in skill like `app-chat` is under `~/agent/core/skills/<name>/cli`):

```bash
uv tool install --editable --force --reinstall <source-dir>
```

This is transactional: a failed rebuild leaves the existing tool exactly as it
was, so you cannot break a working tool by trying.

### Compiled tools (Go, Rust, and similar)

These should be a small launcher that recompiles from source on each run, the way
`whatsapp` and `telegram` do, never a static binary built once and left on PATH.
If one of your compiled skills is a build-once binary, switch it to its launcher
(follow that skill's SETUP).

### Confirm

You are done when every skill tool resolves to live source: re-run the Python
check above and it prints nothing, and each compiled tool is a launcher rather
than a build-once binary. A running daemon keeps its old code until its next
restart, which happens on the next container restart, so you do not need to
restart anything by hand.
