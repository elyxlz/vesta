---
interruptible: true
---

The voice skill is one service with three parts that are built to work together: the engine (the
`/voice/session` socket, which decides turns, barge-in, and playback), the providers behind the
three roles `stt`, `tts`, and `judge`, and the `voice` command. A stock file that carries a local
change from a different design can load without an error and then fail in the middle of a session.

This box can hold voice work of its own: a change inside the voice skill, a provider or a local
model that you added, or code in a different place that talks to the voice service. This migration
saves that work, makes the voice skill equal to stock, and then you build your work again on the
stock interfaces. On a box with no voice work of its own, steps 2 to 4 are the whole job and take
about a minute. Every step checks before acting, so this is safe to run more than once, and a user
message can interrupt it.

Your keys, your selected providers, and your settings are in `~/.voice/voice_config.json`. Step 4
can add one behavior to that file with the `voice` command, and no step removes anything from it.
Do not ask the user for a key.

### 1. Check that the workspace is ready

```bash
cd ~
git rev-parse -q --verify MERGE_HEAD >/dev/null && echo merge-in-progress
VERSION="$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
TAG="agent-v$VERSION"
git merge-base --is-ancestor "$TAG" HEAD && echo synced || echo not-synced
```

- `merge-in-progress`: finish the merge as `~/agent/core/skills/upstream-sync/SKILL.md` says, then
  run this step again.
- `not-synced`: the workspace does not have the stock voice skill of your version. STOP and leave
  this migration unmarked. It runs again on the next boot, after the sync.
- `synced`: continue. A shell variable does not last from one command to the next, so each later
  block that needs `$TAG` sets it again.

### 2. Save your voice work, then take the stock skill

```bash
cd ~
TAG="agent-v$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
mkdir -p ~/.voice
[ -f ~/.voice/own-work.patch ] || {
  git add -A agent/skills/voice &&
  git diff --cached --binary "$TAG" -- agent/skills/voice > ~/.voice/own-work.tmp &&
  mv ~/.voice/own-work.tmp ~/.voice/own-work.patch
}
[ -f ~/.voice/stock-taken ] || {
  git restore --source="$TAG" --staged --worktree -- agent/skills/voice &&
  { git diff --cached --quiet || git commit -qm "voice: take the stock skill"; } &&
  touch ~/.voice/stock-taken
}
```

`~/.voice/own-work.patch` now holds each line where your voice skill was different from stock: a
`+` line is yours, and a `-` line is a stock line that you removed. An empty file means that you
changed nothing. The file is written one time and never again, so a second run cannot replace it
with an empty one.

The upstream-sync skill tells you to keep both sides of a conflict. The voice skill is the one
exception, for the reason at the top. Nothing is lost, because the patch file has each line.

Then find your voice work outside the skill. Only a file that you changed or created can hold it:

```bash
cd ~
TAG="agent-v$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
{ git diff --name-only "$TAG" -- agent; git ls-files --others --exclude-standard -- agent; } \
  | sort -u | grep -v '^agent/skills/voice/' | tr '\n' '\0' \
  | xargs -0 -r grep -nE "stt/listen|tts/(speak|prepare|stream)|voice_config\.json|services/voice"
```

Also think of what no search can find: a speech model or a speech server that you run on this box,
and a device or a bridge that you built for voice (a room speaker, a phone line).

### 3. Refresh the voice CLI and start the daemon again

```bash
uv tool install --editable ~/agent/skills/voice/cli
voice daemon status
```

If the status prints `"running": true`, run `voice daemon restart`. Then:

```bash
voice status
```

It must print one line of JSON with the roles `stt`, `tts`, and `judge`. If it fails, read
`~/agent/logs/voice.log`. If it names a provider that the skill does not know, that provider is
part of your own work: build it in step 5, then run this step again.

### 4. Keep the user's choice about interruptions

The behavior `barge_in` decides if the user's voice stops a reply that you speak. A box whose
user turned that off can hold the choice under the key `interrupt_tts`, which nothing reads.

```bash
python3 - <<'EOF'
import json, pathlib
try:
    config = json.loads((pathlib.Path.home() / ".voice/voice_config.json").read_text())
except (OSError, ValueError):
    config = {}
stt = config["stt"] if "stt" in config and config["stt"] else {}
behavior = config["behavior"] if "behavior" in config and config["behavior"] else {}
off = "interrupt_tts" in stt and stt["interrupt_tts"] is False
print("move" if off and "barge_in" not in behavior else "nothing-to-move")
EOF
```

- `move`: run `voice behavior set barge_in off`.
- `nothing-to-move`: continue.

### 5. Build your work again on the stock interfaces

If `~/.voice/own-work.patch` is empty, the search of step 2 printed nothing, and you run no speech
model or device of your own, you have nothing to build. Go to step 7.

Read these first: the "Own providers" section of `~/agent/skills/voice/SKILL.md`, and
`~/agent/skills/voice/PROTOCOL.md`. Then read the whole patch file and each hit of the search. If
the patch is long, give each piece to a subagent, and apply the results yourself.

Decide for each piece of work where it goes:

| Your work | Where it goes |
| --- | --- |
| A fix, or a feature that stock now has | Nowhere. Drop it. |
| A different vendor, or a model that runs on this box, for speech to text, text to speech, or the barge-in decision | One provider file and one line in `providers/own.py`, as "Own providers" says. A local model runs in its own process, and the provider is a client of it. |
| A changed default or a tuned value | A setting: `voice <role> set <key> <value>` or `voice behavior set <key> <value>`. |
| A voice that you added | `voice tts voices add <id> --name <name>`. |
| Your own rule for the end of a turn, for barge-in, or for when to play a reply | Nowhere. The engine owns these decisions. Tune them with the settings. If you need a different answer to "who are these words for" or "does the user want me to stop", that is a `judge` provider. |
| Code that opens the mic socket or fetches speech audio for a device or a channel of your own | A client of `/voice/session`, as `PROTOCOL.md` says. `/stt/listen` and the `/tts/` routes serve the stock app and the stock skills only. Your client keeps what belongs to it: the chat, the queue of its device, and when a session starts and ends. |
| Work that fits no row | Do not put it into a stock file. Keep the patch file, and tell the user in step 7 what it is and why it has no place. If it helps each Vesta, propose it with `~/agent/skills/upstream/SKILL.md`. |

One rule decides if you are done. This command must list only `providers/own.py`, your own
provider files, and your own rows in the tests:

```bash
cd ~
TAG="agent-v$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
git diff --stat "$TAG" -- agent/skills/voice
```

Each other stock file stays equal to stock, because an update merges new stock lines into it, and
a local change there conflicts or breaks at each update.

### 6. Check that it works

```bash
uv run --project ~/agent/skills/voice/cli pytest ~/agent/skills/voice/cli/tests/ -q
voice daemon restart
voice status
```

- The tests must pass, with one row for each provider that you added.
- For each provider that you added, run `voice <role> check <name>`. It must succeed.
- `voice status` must show the same selected provider for each role as before this migration. If
  your own provider was the selected one, select it again with `voice <role> use <name>`.
- For a client that you moved to `/voice/session`: open one session, check that a `state` frame
  arrives, send one `speak`, and check that a `play` frame arrives.

Fix what fails before you continue. Then commit:

```bash
git -C ~ add -A && { git -C ~ diff --cached --quiet || git -C ~ commit -m "voice: my work on the stock interfaces"; }
```

### 7. Tell the user, and mark this migration applied

If you built something again, or you could not, tell the user in a few lines: what works as
before, what works in a different way, and what you did not build and why. If you had no voice
work of your own, say nothing.

Keep `~/.voice/own-work.patch`. It is the record of your earlier work.

Call `mark_migration_applied` with `name="2026-10-voice-engine"`.
