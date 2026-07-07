---
name: contacts
description: The people Vesta knows, a living address book and CRM. Who they are, how they communicate, what you know about them, and the history. Use whenever a person comes up, someone new appears, or you learn something about anyone in the user's world. Read a contact before reaching out to them; update it after.
---

# Contacts

Your memory of people. Everyone in the user's world gets a file: who they are, how they talk, what you know, what's open between them and the user. This is how you stop treating each person like a stranger. Before you message someone, read their file. After you learn something, write it down. Over time this becomes the thing that lets you sound like you actually know them.

Keep it plain. The whole thing is markdown you edit with Read, Write, Glob, and Grep. No CLI, no database.

## Where it lives

`~/.contacts/` (personal, never leaves this box):

- `INDEX.md`: the roster. One line per person: `name, relationship, one-liner`. Scan this first to see who you know.
- `<slug>.md`: one file per person (`mom.md`, `jane-cofounder.md`, `emilio.md`). Slug is lowercase, dashes for spaces.

`Glob ~/.contacts/*.md` to list everyone. `Grep` across the dir to find who said what or who works where.

## What a person's file holds

Flexible, not a form. Lead with the header line, then whatever you actually know. A good file for someone close:

```markdown
# Jane Rossi

Relationship: co-founder, closest work relationship
Channels: whatsapp +39..., jane@company.com, telegram @jane
Aliases: Jane, JR

## Who they are
Sharp, fast, allergic to fluff. Runs product. Two kids, plays tennis Sundays.

## How they communicate
Terse on WhatsApp, formal on email. Hates long messages. Responds fast in the
morning, goes dark after 6pm. Sarcasm lands; corporate tone does not.

## What I know
- Pushing the Q3 launch, stressed about the deadline
- Vegetarian, coffee snob
- Birthday March 4

## History / open threads
- 2026-07-02 asked the user to review the deck, still pending
- Owes the user dinner from the bet they lost
```

Only fill what's real. A near-stranger might be three lines. Someone central might be a page. Personality and communication style matter most, they're what change how you actually talk to and about this person.

## When to touch it

- **Someone new appears** (a new sender, a name the user mentions, a person on the calendar): add a file and an INDEX line, even if it's just a stub.
- **You learn something**: append it to their file. A preference, a date, a mood, a fact, a thing they're going through. Small and often beats a big rewrite.
- **Before reaching out**: read their file so you match their style and remember what's open.
- **The user asks about someone**: their file is your first stop, then `recall` for anything not captured yet.

Keep INDEX.md in sync with the files. It's the fast path; the files are the depth.

## Keeping your sources in sync

People don't live in one place. The same person is a WhatsApp thread, an email address, a calendar guest, maybe a row in Google or Microsoft contacts. Contacts is the hub of truth that ties those together, and you keep them reconciled in both directions:

- **Pull in**: new people and new facts from the connected sources (whatsapp, email, calendar, the address book skills) get folded into the contact files. A new sender becomes a new file; a phone number you learn gets added to Channels.
- **Push out**: when a service has a write API (Google contacts, Microsoft contacts), keep its canonical fields (name, number, email) matching what you know here. Non-destructive: fill gaps and fix what's clearly stale, never bulk-overwrite a service's data.

Do this on a schedule so it stays current without the user asking. Keep exactly **one** recurring reminder that triggers the pass:

```bash
tasks remind "Reconcile contacts across whatsapp, email, calendar, and the address books" --recurring weekly --at "2026-01-05T09:00:00" --tz "$TZ"
```

When that reminder fires, run the reconcile: sweep each connected source, merge new people and facts into `~/.contacts/`, then update the writable address books to match. Check `tasks remind list` before adding another so you never stack duplicates. If the user has no contact-holding services connected yet, skip the reminder until they do.

## [Your setup]

[Fill in as you go: which contact sources this user has connected (whatsapp, google, microsoft, ...), which ones you sync outward to, how often the user wants the reconcile to run, and any people or circles that matter most.]
