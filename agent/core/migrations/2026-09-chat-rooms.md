The app's chat skill is named `chat`: its directory is `~/agent/skills/chat/`, its command is `chat`, its data lives in `~/.chat/`, its notifications carry `source=chat`, and its daemon line is `chat daemon start`. Your box still holds the installed tool, the data directory, the service registration, the daemon line, and any notification rules under the old name `app-chat`. Every step reads disk state first, so this is safe to run more than once.

### 1. Stop the old daemon by its pid record

```bash
PID=$(cut -d' ' -f1 ~/agent/data/daemons/app-chat.pid 2>/dev/null); [ -n "$PID" ] && kill "$PID" 2>/dev/null; rm -f ~/agent/data/daemons/app-chat.pid ~/agent/data/daemons/app-chat.port; echo stopped
```

SIGTERM is the deliberate stop, so this fires no `daemon_died`. A missing record means nothing was running.

### 2. Move the data directory

```bash
[ -d ~/.app-chat ] && [ ! -d ~/.chat ] && mv ~/.app-chat ~/.chat
cd ~/.chat 2>/dev/null && for f in app-chat.db app-chat.db-wal app-chat.db-shm; do [ -f "$f" ] && mv "$f" "chat${f#app-chat}"; done; rm -f ~/.chat/app-chat.sock; ls ~/.chat
```

The listing must show `chat.db` and no `app-chat.db`. A box with no `~/.app-chat` never chatted and has nothing to move; continue. This step runs before the reinstall: until then no daemon can start, so nothing creates `~/.chat` ahead of the move.

### 3. Reinstall the command under its new name

```bash
uv tool uninstall app-chat-cli 2>/dev/null; uv tool install --editable --force ~/agent/skills/chat/cli
command -v chat
```

The last line must print a path under `~/.local/bin`. If it does not, STOP and leave this migration unmarked.

### 4. Re-register the service and fix the daemon line

```bash
deregister-service app-chat 2>/dev/null; sed -i 's/^app-chat daemon start/chat daemon start/' ~/agent/skills/restart/daemons.sh; grep -c '^chat daemon start' ~/agent/skills/restart/daemons.sh
```

The count must be 1. If it is 0, add the line `chat daemon start` to `~/agent/skills/restart/daemons.sh` yourself. Then:

```bash
chat daemon start
```

It must print `{"status":"started"}` or `{"status":"already_running"}`.

### 5. Drop the stale name from the active skill list

```bash
~/agent/skills/skills-registry/scripts/skills-deactivate app-chat
```

`chat` is a default skill and activates on every boot, so nothing has to be added.

### 6. Rewrite your notification rules

Run `notifications list`. For each rule whose `source` is `app-chat`, run `notifications add` with the same `--type`, `--match`, `--action`, and `--for` values but `--source chat`, then `notifications remove <id>` for the old rule. Rules under any other source stay. No rule under `app-chat` means nothing to do.

### 7. Update your own notes

```bash
grep -l 'app-chat' ~/agent/MEMORY.md ~/agent/skills/personality/*.md 2>/dev/null | xargs -r sed -i 's/app-chat/chat/g'; grep -c 'app-chat' ~/agent/MEMORY.md || true
```

The count must be 0.

### 8. Mark this migration applied

Call `mark_migration_applied` with this migration's name.
