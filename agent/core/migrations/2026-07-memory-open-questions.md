MEMORY.md's User State section now tracks 1-3 standing "Open questions about
them", things you genuinely don't understand about who the user is, so the
dream has something concrete to work on each night instead of relying on
starting from zero. Section 4 also gained a way to point at the user's own
`~/.contacts/` file for depth that outgrows MEMORY.md (see the `contacts`
skill). Boxes whose MEMORY.md predates both never got either line. This
migration adds what's missing and is a no-op if you already have them.

### 1. Add the open-questions field

Open `~/agent/MEMORY.md` and find the User State block in section 4 (the
`**Focus**:` / `**How it's going**:` / ... lines). If there is no
`**Open questions about them**:` line, add one directly after
`**Open threads**:`, matching the other fields' formatting. Leave it empty for
now; the next dream fills it in.

### 2. Point Important Contacts at the contacts store

Still in section 4, find `### Important Contacts`. If its placeholder text
doesn't already mention `~/.contacts/`, note there that the user's own deeper
profile (the full history and texture that outgrows this section) lives in
`~/.contacts/`, per the `contacts` skill. Don't touch anything else in that
section, real content included.
