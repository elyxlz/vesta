Every saved WhatsApp contact name must point at one person. A reply to a direct
WhatsApp message addresses a saved contact by name, so two different people
saved under the same name make that reply fail as ambiguous. This migration
renames such contacts apart. It is safe to run more than once: it only renames
names that still collide.

### 1. Skip if WhatsApp is not set up

If `~/agent/skills/whatsapp` does not exist, you never installed the skill.
Skip to the final step.

### 2. List saved contacts

```bash
whatsapp list-contacts --limit 1000
```

Each entry has a `name` and a `phone_number`. Only an entry with `"is_manual": true` is a saved
contact. An entry without that field is a chat the user never saved: skip it, and use only the
saved contacts in the next step.

### 3. Rename apart any name two different people share

Group the contacts by name, ignoring case and surrounding spaces. A name is a
problem only when two or more genuinely different people hold it. One person
saved under both a phone number and a chat id is not a collision, so leave them.

For each name that two different people share, give all but one of them a
distinct name. Address each by their exact phone number, so the rename updates
that person and not the other:

```bash
whatsapp add-contact --name "Emmy R" --phone "+447700900123"
```

Pick a name that tells them apart from what you know about them: a surname
initial, their relationship, or where you know them from. Do not invent a detail
you do not know. If you cannot tell two people apart, ask the user which name
each should have.

A colliding contact with no phone number is saved by a chat id, which this list
does not show. Rename the others instead, so the bare name points at that one
person.

### 4. Mark this migration applied

Call `mark_migration_applied` with `name="2026-08-whatsapp-unique-contact-names"`.
