Every saved Telegram contact name must point at one person. A send to a saved
contact by name (`telegram send --to '<name>'`) reaches the wrong person when
two different contacts share that name. This migration renames such contacts
apart. It is safe to run more than once: it only renames names that still
collide.

### 1. Skip if Telegram is not set up

If `~/agent/skills/telegram` does not exist, you never installed the skill.
Skip to the final step.

### 2. List saved contacts

```bash
telegram list-contacts --limit 1000
```

Each entry has a `name` and a `chat_id`. Only an entry with `"is_manual": true`
is a saved contact. An entry without that field is a chat the user never saved:
skip it, and use only the saved contacts in the next step.

### 3. Rename apart any name two different people share

Group the saved contacts by name, ignoring case and surrounding spaces. A name
is a problem only when two or more different chat ids hold it.

For each name that two different people share, give all but one of them a
distinct name. Address each by their exact `chat_id`, so the rename updates that
person and not the other:

```bash
telegram add-contact --name "Sarah R" --chat-id 123456789
```

Pick a name that tells them apart from what you know about them: a surname
initial, their relationship, or where you know them from. Do not invent a detail
you do not know. If you cannot tell two people apart, ask the user which name
each should have.

### 4. Mark this migration applied

Call `mark_migration_applied` with `name="2026-08-telegram-unique-contact-names"`.
