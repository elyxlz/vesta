---
name: transcript
description: Extract and compress SDK session messages into a portable transcript for nap/dreamer handoff.
---

# Transcript — Session Context Extraction & Compression

Extracts the full conversation history from the Claude SDK session and compresses it into a clean, readable text file. The output preserves what matters for memory curation (decisions, discussions, events) while stripping mechanical noise (tool results, thinking blocks, raw file contents).

Designed as the first stage of a two-phase nap/dream process:
1. **Extract & compress** (this skill) — save the session transcript to disk before clearing the session
2. **Curate** (dream skill) — process the transcript into memory updates with a clean context window

## When to use

- Before a nap or context reset — save the session so the dreamer has material to work with
- Before auto-compact is likely to fire — preserve the full transcript while it still exists
- On demand — snapshot the current session for inspection or debugging

## Scripts

### `extract.py` — Pull raw session messages from the SDK

```bash
python3 ~/vesta/skills/transcript/scripts/extract.py [output.json]
```

Reads the current session ID from the data directory and calls `get_session_messages()`. Saves the raw message list as JSON. If no output path is given, writes to `~/vesta/data/session_transcript.json`.

### `compress.py` — Clean and compress a raw transcript

```bash
python3 ~/vesta/skills/transcript/scripts/compress.py <input.json> [output.txt]
```

Takes raw session JSON and produces a readable text file:

**Keeps:**
- All user messages (verbatim) — direct input, WhatsApp notifications, voice transcriptions
- All assistant text responses (verbatim) — this is where decisions and explanations live
- WhatsApp group messages tagged with `[WA group: name]` so the dreamer can scan for signal
- Tool use compressed to one-liners: `[Edited /path/file.py]`, `[Ran: git status]`

**Drops:**
- Thinking blocks (internal reasoning — not useful for memory)
- Tool results (file contents, command output — bulk noise)
- System reminder blocks (SDK-injected boilerplate)

**Typical compression:** ~70-75% size reduction (e.g., 855 KB raw → 233 KB compressed).

### Full pipeline

```bash
# Extract current session
python3 ~/vesta/skills/transcript/scripts/extract.py ~/vesta/data/session.json

# Compress it
python3 ~/vesta/skills/transcript/scripts/compress.py ~/vesta/data/session.json ~/vesta/data/session_compressed.txt
```

The compressed file is then ready to be:
- Fed to an external summarizer (e.g., ChatGPT) for further compression
- Read directly by the dreamer for memory curation
- Archived for debugging or context reconstruction

## Design notes

- Group chat messages are kept but tagged — a cluster of easter greetings is noise, but a funding discussion buried in a group chat is not. The dreamer (or external summarizer) makes that judgment call.
- The previous session's compaction summary (if present) is preserved — it provides continuity across sessions.
- Tool one-liners are collapsed into blocks rather than scattered across the transcript.
