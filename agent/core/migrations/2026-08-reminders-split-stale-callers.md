Find and rewrite stale `tasks remind` callers. The tasks CLI has no `remind` subcommand: reminders
are their own `reminders` CLI. A caller that still spells the old command fails when it runs, and
two spellings survive a plain grep for `tasks remind`: a programmatic caller that passes the
command as separate tokens, and a recurring reminder whose own message tells you to run the old
command when it fires.

### 1. Sweep the source tree for both spellings

```bash
grep -rnE "tasks[][\"', ]+remind" ~/agent/MEMORY.md ~/agent/skills --exclude-dir=cli --exclude-dir=.venv
```

The pattern matches the shell form (`tasks remind`) and the token form (`"tasks", "remind"`).
Rewrite each hit in place:

- `tasks remind "..." <flags>` becomes `reminders create "..." <flags>`
- `tasks remind list|snooze|update|delete` becomes `reminders list|snooze|update|delete`
- a token-form caller drops the `remind` token and replaces `tasks` with `reminders`, with the same
  subcommand mapping: `["tasks", "remind", "list", "--json"]` becomes `["reminders", "list", "--json"]`
- a `--task <id>` flag has no equivalent: drop it and name the task in the message instead

No hits means nothing to rewrite.

### 2. Sweep the reminders themselves

A recurring reminder's message is an instruction you act on when it fires, so a message spelling
the old command breaks exactly like a script, except it lives in the reminders store where no file
grep can see it, and it surfaces only at fire time.

```bash
reminders list --json-pretty | grep -in 'tasks remind'
```

For each hit, read the reminder's `id` from the surrounding object and rewrite its message with
`reminders update <id> --message '...'`, applying the same substitutions as step 1. No hits means
nothing to rewrite.
