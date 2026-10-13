The voice skill has one command, `voice`, with the grammar `voice <role> <verb>`. The names
`voice-keys` and `voice-server` do not exist, so a caller that spells one fails when it runs. This
box needs the `voice` console script on PATH, the voice daemon running under it, and no caller
left with an old spelling. Every step checks before acting, so this is safe to run more than once.

### 1. Refresh the voice CLI

```bash
uv tool install --editable ~/agent/skills/voice/cli
command -v voice
```

The install is transactional and a re-run over an existing install is a no-op. The last line must
print a path under `~/.local/bin`. If it fails, STOP, leave this migration unmarked, and report it
to the user.

### 2. Fix the daemon line

`~/agent/skills/restart/daemons.sh` is what starts your daemons after a restart. A line that
spells the old name fails there, and voice then stays down with no other sign.

```bash
grep -n "voice-keys\|voice-server" ~/agent/skills/restart/daemons.sh
```

Rewrite each hit to `voice daemon start`. No hit, or no such file, means nothing to rewrite.

### 3. Start the daemon again if it runs

A daemon that was already up still runs the code it loaded at its start.

```bash
voice daemon status
```

- `"running": true`: run `voice daemon restart`, then `voice daemon status` again. It must print
  `"running": true` with a port. If it does not, read `~/agent/logs/voice.log` and fix the cause.
- `"running": false`: this box does not run voice. Leave it down.

### 4. Rewrite your own callers

Stock files already use the new grammar. Only a file that you changed or created can still spell
an old name, so search those:

```bash
cd ~
VERSION="$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
TAG="agent-v$VERSION"
{ git diff --name-only "$TAG" -- agent; git ls-files --others --exclude-standard -- agent; } \
  | sort -u | grep -v '^agent/skills/voice/' | tr '\n' '\0' \
  | xargs -0 -r grep -nE "voice-(keys|server)"
reminders list --json-pretty | grep -in "voice-keys\|voice-server"
```

Rewrite each hit in place. `<role>` is `stt` or `tts`:

| Old spelling | New spelling |
| --- | --- |
| `voice-keys status` | `voice status` |
| `voice-keys validate --provider P --key K` | `voice <role> check P --key K` |
| `voice-keys set-key --domain D --provider P --key K` | `voice D connect P --key K` |
| `voice-keys clear --domain D` | `voice D disconnect P`, one time for each connected provider |
| `voice-keys enable --domain D` / `disable --domain D` | `voice D on` / `voice D off` |
| `voice-keys set-voice --id V` | `voice tts voice V` |
| `voice-keys add-voice --id V --name N` / `remove-voice --id V` | `voice tts voices add V --name N` / `voice tts voices remove V` |
| `voice-keys add-keyterm T` / `remove-keyterm T` | `voice stt keyterms add T` / `voice stt keyterms remove T` |
| `voice-keys set-eot --threshold X` | `voice stt set eot_threshold X` |
| `voice-keys set-eot --timeout-ms N` | `voice stt set eot_timeout_ms N` |
| `voice-keys daemon <verb>` | `voice daemon <verb>` |
| `voice-server` | never started by hand: `voice daemon start` |

A hit in a reminder is in its message: rewrite it with `reminders update <id> --message '...'`.
No hits means nothing to rewrite.

### 5. Mark this migration applied

Call `mark_migration_applied` with `name="2026-10-voice-command"`.
