You now have a `contacts` skill: a living CRM where every person in the user's
world gets a markdown file (personality, communication style, what you know,
history) under `~/.contacts/`. Existing boxes have people scattered across
memory and past conversations but no contact files yet. This migration seeds
them. It is safe to run more than once: it only adds what is missing.

### 1. Make sure the skill is installed

If `~/agent/skills/contacts/SKILL.md` does not exist, install it:

```bash
~/agent/skills/skills-registry/scripts/skills-install contacts
```

Then Read the SKILL.md so you follow its structure (INDEX.md plus one file per
person).

### 2. Seed contact files from what you already know

Build your initial roster from the people you already have context on. Cover:

- **MEMORY.md**: the user, their family, coworkers, friends, anyone named.
- **Past conversations**: use the `recall` skill to surface people who come up
  (names, senders, recurring characters) that memory does not capture.
- **Connected sources**: if whatsapp, email, calendar, or an address book skill
  (google, microsoft) is set up, pull the people the user actually talks to.

For each person, create `~/.contacts/<slug>.md` with what you genuinely
know (relationship, channels/handles, personality, communication style, facts,
open threads) and add a line to `~/.contacts/INDEX.md`. Do not invent
details. A near-stranger can be three lines; skip anyone you know nothing about.
If a person already has a file, only add what is missing, never overwrite.

### 3. Set up the recurring sync (only if the user has contact sources)

If any contact-holding service is connected (whatsapp, google, microsoft,
calendar) and you do not already have a reconcile reminder (`tasks remind list`),
schedule one so the sources stay consistent both ways, as described in the
skill's "Keeping your sources in sync" section. If nothing is connected yet,
skip this step.
