The reminders daemon emits two notification types with `source=reminders`: `type=reminder_due`
when a reminder fires on schedule, and `type=reminder_missed` when a one-shot is replayed on
restart because its time passed while the daemon was down. Skill code that ran before this boot
emitted both as `type=reminder`, so anything on this box keyed to `source=reminders` with
`type=reminder` now points at a type the daemon no longer writes. If the reminders skill is not
active on this box, every step below is a no-op.

### 1. Restart the reminders daemon

The daemon loaded its code when it started, so until it restarts it keeps emitting the old type:

```bash
reminders daemon restart
```

### 2. Update notification rules that target the old pairing

```bash
notifications list
```

A rule with `type=reminder` that catches the reminders skill (either `source=reminders` or no
`source`) no longer matches anything. The old `type=reminder` caught every reminder, on-schedule
and missed alike, so decide what the rule was for and re-create it with `notifications remove <id>`
then `notifications add` (same action and conditions, `--before`/`--after` to keep its position):

- Only on-schedule reminders: `--source reminders --type reminder_due`.
- Only missed one-shots: `--source reminders --type reminder_missed`.
- Both, as before: re-create it for `reminder_due` and add a second rule for `reminder_missed`.

Ask the user when the intent is not clear from the rule.

### 3. Sweep your own references to the old pairing

```bash
grep -rniE "type[\"'=: ]+reminder\b" ~/agent/MEMORY.md ~/agent/skills --exclude-dir=cli --exclude-dir=.venv
```

Each hit that means a reminders notification now spells `type=reminder_due` (on-schedule) or
`type=reminder_missed` (missed). Rewrite it to the one it meant. No hits means nothing to rewrite.
