Every WhatsApp account this container serves needs its own `whatsapp daemon start` line in `~/agent/skills/restart/daemons.sh`. A `whatsapp` command talks to a running daemon and starts none, so an account with no line there stays down after a restart, and every message that arrives while it is down is lost with no trace. Safe to run more than once: each step reads what is on disk first.

### 1. Stop if this container has no WhatsApp

```bash
test -d ~/.whatsapp && echo yes || echo no
```

If it prints `no`, go to step 5.

### 2. List the accounts and the lines you have

```bash
find ~/.whatsapp -maxdepth 2 -name whatsapp.db
cat ~/agent/skills/restart/daemons.sh
```

`~/.whatsapp/whatsapp.db` is the default instance (`whatsapp daemon start`, no `--instance`). Every `~/.whatsapp/<name>/whatsapp.db` is the instance `<name>` (`whatsapp daemon start --instance <name>`).

### 3. Add a line for each account that has none

Read each account's `state.json` (the file beside its `whatsapp.db`). Its `args` field is the flag set that account runs with, and an absent field means none. Put those flags on the account's line, minus `--notifications-dir`, which the command applies itself. Create `daemons.sh` if it does not exist, with the header the `restart` skill documents. One account per line, for example:

```bash
whatsapp daemon start
whatsapp daemon start --instance personal --read-only
```

Leave out any account you are deliberately holding offline, and change no line that is already there.

### 4. Start what is down

```bash
~/agent/skills/restart/start-daemons.sh
```

### 5. Mark this migration applied

Call `mark_migration_applied` with `name="2026-08-whatsapp-restart-line"`.
