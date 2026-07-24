Your `whatsapp` command is a static binary compiled once at setup. It never
gets rebuilt, so source fixes to the whatsapp skill silently never reach it,
and its bundled whatsmeow protocol code ages until WhatsApp breaks it
(issue #1073). The skill now ships a launcher script (`whatsapp` in the skill
directory) that compiles
from source on every invocation and pulls the latest whatsmeow before the
daemon starts. This migration switches you onto that launcher. Every step is
safe to run more than once.

### 1. Skip if WhatsApp is not set up

If `~/agent/skills/whatsapp` does not exist, you never installed the skill:
skip to the final step.

### 2. Check the build toolchain is still present

The launcher needs the Go toolchain and the whisper.cpp static libraries that
were installed when the skill was set up:

```bash
ls /usr/local/go/bin/go /opt/whisper.cpp/build-static 2>&1
```

If either is missing, redo steps 1 and 2 of
`~/agent/skills/whatsapp/SETUP.md` first (install dependencies, build
whisper.cpp).

### 3. Install the launcher and delete the stale binaries

```bash
mkdir -p ~/.local/bin
ln -sf ~/agent/skills/whatsapp/whatsapp ~/.local/bin/whatsapp
rm -f /usr/local/bin/whatsapp
```

`ln -sf` also replaces any old static binary sitting at `~/.local/bin/whatsapp`.

### 4. Prime the build, then restart the daemon

Compile before restarting so the daemon is only down for seconds, not for the
minutes the first compile takes:

```bash
whatsapp --help
```

Wait for it to finish (a few minutes on first run). If it fails, fix the
toolchain per step 2 before touching the daemon. Then, only if a whatsapp
screen session is actually running, restart it onto the launcher:

```bash
if screen -ls | grep -q '\.whatsapp[[:space:]]'; then
  screen -S whatsapp -X quit
  sleep 2
  screen -dmS whatsapp whatsapp serve --notifications-dir ~/agent/notifications
fi
```

If you run extra instances (e.g. `--instance personal`), restart those screen
sessions the same way with their original serve flags.

After ~30 seconds, confirm the session survived the restart:

```bash
whatsapp authenticate
```

It should report already authenticated. If it does not, tell the user their
WhatsApp link needs re-pairing and follow SETUP.md's auth section.

### 5. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-whatsapp-live-build"`.
