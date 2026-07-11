The nightly contacts pass (capture everyone who came up today, then reconcile
the sources) is now owned by the `dream`, not a standalone reminder. Earlier
boxes created a dedicated recurring reminder for it: the old `contacts` skill
and the `2026-07-contacts-backfill` migration both set one up. This migration
removes that reminder so the pass does not run twice a night. It is safe to run
more than once and is a no-op if you never had one.

### 1. Delete the standalone contacts reminder

If the `tasks` skill is set up, list your recurring reminders:

```bash
tasks remind list
```

Find the one whose message is about updating contacts and reconciling them
across services (the old wording was roughly "Update contacts with everything
learned today, then reconcile them across every messaging app..."). If it
exists, delete it by id:

```bash
tasks remind delete <id>
```

If there is no such reminder, or the `tasks` CLI is not installed, there is
nothing to remove. Either way the `dream` now runs this pass nightly in its
"User State" step, so nothing is lost.

### 2. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-contacts-reminder-to-dream"`.
