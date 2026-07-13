---
name: contacts
description: The people Vesta knows, a living address book and CRM. Who they are, how they communicate, what you know about them, and the history. Use whenever a person comes up, someone new appears, or you learn something about anyone in the user's world. Read a contact before reaching out to them; update it after.
---

# Contacts

Your memory of people. Everyone in the user's world gets a file: who they are, how they talk, what you know, what's open between them and the user. Before you message someone, read their file; after you learn something, write it down. Over time this lets you sound like you actually know them.

Plain markdown, edited with Read, Write, Glob, Grep. No CLI, no database.

## Where it lives

`~/.contacts/` (personal, never leaves this box), one markdown file per person: `mom.md`, `jane-cofounder.md`. Slug is lowercase, dashes for spaces. No index, the files are the whole thing.

Derive the roster from the files instead of keeping a separate list:

```bash
grep -rHs "^# \|^Relationship:" ~/.contacts/   # name + relationship for everyone; empty until you add people
```

`Glob ~/.contacts/*.md` lists everyone; `Grep` across the dir finds who said what or who works where.

## What a file holds

Flexible, not a form. Lead with the header line, then whatever you actually know:

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

Only fill what's real. A near-stranger might be three lines; someone central a page. Personality and communication style matter most, they change how you talk to and about this person.

## When to touch it

- **Someone new appears** (new sender, a name the user mentions, a person on the calendar): add a file, even just a stub.
- **You learn something**: append it. Small and often beats a big rewrite.
- **Before reaching out**: read their file to match their style and remember what's open.
- **The user asks about someone**: their file first, then `recall` for anything not captured yet.

## Keeping contacts current

Two things keep the files honest, both on one nightly pass in the early hours (the nightly `dream` runs it, no separate reminder):

- **Capture the day**: fold everything you learned about anyone into their file, a new fact, mood, plan, a handle you saw. Anyone new that day gets a file.
- **Reconcile the sources**: the same person is a thread in one app, an address in another, a calendar guest, an address-book row. Contacts is the hub of truth. Pull new people and facts in from everywhere that holds contacts, and push your canonical fields (name, number, email) back out to writable services. Non-destructive: fill gaps and fix clearly-stale data, never bulk-overwrite a service.

## [Your setup]

[Fill in as you go: which contact sources this user has connected (whatsapp, google, microsoft, ...), which ones you sync outward to, how often the user wants the reconcile to run, and any people or circles that matter most.]
