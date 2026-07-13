Your skills reach the world through their command line tools. Each of those
tools should run from its **live source** under `~/agent`, so that when a skill's
source is updated (by you, or by upstream sync) the change actually takes effect.
A tool installed as a frozen, build-once artifact instead keeps running the code
it was built from, so fixes to that skill silently never reach it. The symptom
that surfaced this: the app-chat skill delivering every app message to you twice,
because a stale copy and the live agent were both writing the notification. Any
skill can drift the same way.

Go through your installed skill tools and make sure each one runs from live
source, not a frozen snapshot. Use your judgement: you know which skills you have
and how you installed them. This is safe to redo.

### Python tools (installed with `uv tool`)

These should be **editable** installs, linked to their source, not frozen copies.
See which of yours are frozen (this only reads):

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

For each frozen one, reinstall it editable from the skill's **current** source
directory (usually the path shown; if a skill has moved, find where it lives now,
for example a built-in skill like `app-chat` is under
`~/agent/core/skills/<name>/cli`):

```bash
uv tool install --editable --force --reinstall <source-dir>
```

Reinstalling is transactional: if it fails, the existing tool is left exactly as
it was, so you cannot break a working tool by trying.

### Compiled tools (Go, Rust, and similar)

These should be a small launcher that recompiles from source on each run, the way
`whatsapp` and `telegram` do, never a static binary built once and left on PATH.
If one of your compiled skills is a build-once binary, switch it to its launcher
(follow that skill's SETUP).

### The principle

Whatever the language, the command on your PATH should resolve to live source,
never a frozen snapshot. Any skill tool that does not, fix so that it does. A
running daemon keeps its old code until its next restart, which happens on the
next container restart, so you do not need to restart anything by hand. Once
every one of your skill tools runs from live source, this is done.
