---
name: contacts
description: The people Vesta knows, a living address book and CRM. Who they are, how they communicate, what you know about them, and the history. Use whenever a person comes up, someone new appears, or you learn something about anyone in the user's world. Read a contact before reaching out to them; update it after.
---

# Contacts

Your memory of people. Everyone in the user's world gets a file: who they are, how they talk, what you know, what's open between them and the user.

Keep it plain. The whole thing is markdown you edit with Read, Write, Glob, and Grep. No CLI, no database.

## Where it lives

`~/.contacts/` (personal, never leaves this box), one markdown file per person: `mom.md`, `jane-cofounder.md`, `sam-brother.md`. Slug is lowercase, dashes for spaces. No index and no database, the files are the whole thing.

The user themselves never gets a contact file. They matter too much to page out: the full profile, history, and texture live in MEMORY.md's USER PROFILE and stay in memory. Contacts are the other people in the user's world.

To see who you know, derive the roster from the files instead of keeping a separate list (nothing to fall out of sync):

```bash
grep -rHs "^# \|^Relationship:" ~/.contacts/   # name + relationship for everyone; empty until you add people
```

`Glob ~/.contacts/*.md` lists everyone; `Grep` across the dir finds who said what or who works where.

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

- **Someone new appears** (a new sender, a name the user mentions, a person on the calendar): add a file, even if it's just a stub.
- **You learn something**: append it to their file. A preference, a date, a mood, a fact, a thing they're going through. Small and often beats a big rewrite.
- **Before reaching out**: read their file so you match their style and remember what's open.
- **The user asks about someone**: their file is your first stop, then `recall` for anything not captured yet.

## Which channel is a person actually reading

A contact file records how someone communicates; it does not know which channel they are on *now*.
`scripts/live-channel.sh` answers that from the event store:

```bash
sh ~/agent/skills/contacts/scripts/live-channel.sh            # every contact with inbound
sh ~/agent/skills/contacts/scripts/live-channel.sh <name>     # one person, ranked by channel
sh ~/agent/skills/contacts/scripts/live-channel.sh --silence-hours
```

**It reads their INBOUND only, never your outbound.** A channel whose recent traffic is all yours is
dead, and that is exactly the case that misleads: you send there, they never see it, and their
silence gets recorded as their answer. The channel they last wrote to you on is the live one.

`--silence-hours` prints hours since the OWNER last wrote, as a bare integer, or the literal
`UNMEASURED` with exit 2. **It never prints a number it did not measure.** A caller that rations on
silence must treat any non-integer as "cannot tell" and ration as though the silence were long: an
unreadable store and a talkative user produce the same output otherwise, and that failure is silent.

Two things it will not do:

- **It never guesses the owner's name.** There is no structured source for it, since the user gets
  no contact file (see above) and the config carries the agent's name rather than theirs. `app-chat`
  is the user's own screen, so inbound there is theirs by construction and needs no name; that is
  the floor and it always works. Set `VESTA_OWNER` to additionally fold in named channels like
  WhatsApp. Without it the answer can only be MORE silence than there really was, never less, which
  rations harder rather than failing open.
- **It never lists a service as a contact.** It reads the event's normalized `sender` field, which
  core populates across `contact_name`, `handle`, `from`, `author` and `sender_address`, so one read
  covers every channel. An empty sender from anything but app-chat is one of your own daemons
  reporting in; those are dropped and named in one line, rather than rendered as a person called `?`
  holding a live channel. Do not scrape the name out of `summary`: that is a per-source presentation
  string, and a channel that attaches `handle` rather than `contact_name` would be silently
  invisible.

## Keeping contacts current

People don't live in one place, and you learn about them all day long. Two things keep the files honest, and you do both on one nightly pass in the early hours:

- **Capture the day**: go back over the day's conversations and activity and fold everything you learned about anyone into their file, a new fact, a mood, a plan, something they're going through, a handle you saw. Anyone who came up for the first time gets a file.
- **Reconcile the sources**: the same person is a thread in one messaging app, an address in another, a guest on a calendar, a row in an address book. Contacts is the hub of truth that ties them together. Pull new people and facts in from everywhere that holds contacts, and push your canonical fields (name, number, email) back out to the services that can be written to. Non-destructive: fill gaps and fix what's clearly stale, never bulk-overwrite a service's data.

The nightly `dream` runs this pass, so there's no separate reminder to maintain.

## [Your setup]

[Fill in as you go: which contact sources this user has connected (whatsapp, google, microsoft, ...), which ones you sync outward to, how often the user wants the reconcile to run, and any people or circles that matter most.]
