The tasks daemon emits a task's due-date checkpoints as notifications with `source=tasks`,
`type=task_due`. Skill code that ran before this boot emitted them as `type=reminder`, the same
type the reminders skill uses for real reminders, so anything on this box keyed to `source=tasks`
with `type=reminder` now points at a type the tasks daemon no longer writes. If the tasks skill is
not active on this box, every step below is a no-op.

### 1. Restart the tasks daemon

The daemon loaded its code when it started, so until it restarts it keeps emitting the old type:

```bash
tasks daemon restart
```

### 2. Update notification rules that target the old pairing

```bash
notifications list
```

- A rule with `source=tasks` and `type=reminder` targets the checkpoints. Re-create it with the
  new type: `notifications remove <id>`, then `notifications add` with the same action and
  conditions but `--type task_due`, using `--before`/`--after` to keep its position.
- A rule with `type=reminder` and no source now matches only the reminders skill's reminders.
  Decide what it was meant to catch: real reminders (leave it), task due-date checkpoints
  (re-create it with `--source tasks --type task_due`), or both (keep it and add a second rule for
  `task_due`). Ask the user when the intent is not clear from the rule.

No rule mentioning `type=reminder` means nothing to update.

### 3. Sweep your own references to the old pairing

```bash
grep -rniE "type[\"'=: ]+reminder" ~/agent/MEMORY.md ~/agent/skills --exclude-dir=cli --exclude-dir=.venv
```

Judge each hit: a reference to the reminders skill's own notifications is correct as it stands; one
that means a task due-date checkpoint now spells `type=task_due`. Rewrite only the latter. No hits
means nothing to rewrite.
