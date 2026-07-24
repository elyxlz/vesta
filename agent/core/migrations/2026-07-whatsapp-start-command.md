The whatsapp skill now has a dedicated `whatsapp start` command: one idempotent
front door that brings the daemon up and waits until it answers, so inbound
WhatsApp notifications are already flowing before you send anything. Your restart
skill's whatsapp line still calls the old form (`whatsapp daemon start`, or a raw
`screen -dmS whatsapp whatsapp serve ...`). This migration points it at
`whatsapp start`. Every step is safe to run more than once and no-ops when
already converged.

### 1. Skip if WhatsApp is not set up

If `~/agent/skills/whatsapp` does not exist, or `~/agent/skills/restart/SKILL.md`
does not exist, there is nothing to convert: skip to the final step.

### 2. Find your whatsapp restart line

Only the `## Daemons` section of your restart skill is affected:

```bash
grep -n 'whatsapp' ~/agent/skills/restart/SKILL.md
```

If the whatsapp line already reads `running whatsapp || { whatsapp start; sleep 1; }`
(or the same with your `--instance` flags), it is already converted: skip to the
final step. If grep finds no whatsapp daemon line at all, skip to the final step.

### 3. Point the line at `whatsapp start`

Replace the whole whatsapp daemon line (whatever start command it currently uses:
`whatsapp daemon start`, or a raw `screen -dmS whatsapp whatsapp serve ...`) with
the guarded new form:

```
running whatsapp || { whatsapp start; sleep 1; }
```

`whatsapp start` defaults the notifications directory to `~/agent/notifications`,
so drop any `--notifications-dir` flag from the old line. If you run a NAMED
instance, keep it on both the guard and the command, e.g. for `personal`:

```
running whatsapp-personal || { whatsapp start --instance personal; sleep 1; }
```

Keep the `running whatsapp ||` guard (defined at the top of the Daemons block):
re-running the block on crash recovery must not stack duplicate daemons. Leave
every other skill's line untouched.

### 4. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-whatsapp-start-command"`.
