---
name: vesta-agent-retro
description: >
  Use when you need to know what a running Vesta agent actually did, for a
  retrospective, postmortem, or "why did the agent do X" question, and a summary is
  not enough because you need its real reasoning and the output its tools returned.
  Triggers: "retrospective on <agent>", "what did <agent> do", "pull/extract the
  agent's transcript", "why did the agent <X>". On the host, needs sudo docker to a
  running vesta-* container.
---

# vesta-agent-retro

Reconstruct a slice of a running Vesta agent's session as a redacted, human-readable
transcript, then write the retrospective on top of it. The agent runs Claude inside a
Docker container; this pulls the real record of a time window out of that container.

Paths below are relative to the repo root. The driver is
`.claude/skills/vesta-agent-retro/extract-retro.sh`.

## The one thing to know first

Two stores hold the agent's history, and only one has tool output:

- `~/agent/data/events.db` (SQLite) has user/assistant messages, **thinking**, and
  **tool calls**, but for a tool it records only that it ran, never what it returned.
- `~/.claude/projects/<slug>/<session_id>.jsonl` (the raw Claude session) has
  **everything**: thinking, tool_use with full input, and **tool_result with full
  output**. This is the source of truth for a retrospective.

So the transcript comes from the `.jsonl`. `events.db` is only useful for a fast
keyword search to find the time window (below).

## Prerequisites

- Run on the host, not inside a container. Docker access. The driver calls `sudo docker`
  itself; on a rootless-docker host, or when you are already root, drop the `sudo` from
  `extract-retro.sh` (it is a thin wrapper).
- A running agent container. List them: `sudo docker ps --format '{{.Names}}' | grep '^vesta-'`.

## Run (the driver)

```bash
# extract-retro.sh <container> <since-iso-utc> <until-iso-utc> [outfile]
.claude/skills/vesta-agent-retro/extract-retro.sh \
  vesta-lucadv-gianfranco 2026-08-17T17:03:00 2026-08-17T17:25:00 retro.txt
```

It reads the agent's live `session_id` from `state.json`, finds the matching `.jsonl`,
runs `extract-transcript.py` inside the container (where the 150MB+ file is local), and
streams back only the filtered slice. Timestamps are **UTC, inclusive, string-compared**,
so keep them zero-padded. Every rendered field is scrubbed for secrets (`wak_` keys, API
keys, tokens); the driver prints a `leak-check:` line to stderr, treat a **non-zero secret
count** as a stop-and-inspect (the same line also reports events rendered, which is not a
warning).

Each record renders as one entry: `USER/CONTEXT`, `THINKING`, `ASSISTANT`, `TOOL CALL
[name]` with its input, or `  -> RESULT:` with the tool output. A multi-line tool output
wraps across several physical lines, so the file's `wc -l` exceeds the "lines rendered"
(logical-event) count in the leak-check line.

## Find the time window

The agent's own timestamps are UTC. To locate a flow by the user's words, search
`events.db` (its FTS indexes inbound messages):

```bash
# -i is required: without it docker exec never attaches the heredoc to python's stdin.
sudo docker exec -i <container> /root/agent/.venv/bin/python - <<'PY'
import sqlite3
db = sqlite3.connect("/root/agent/data/events.db")
q = 'select ts,substr(data,1,80) from events where lower(data) like "%set up whatsapp%" order by id limit 20'
for ts, preview in db.execute(q):
    print(ts, preview)
PY
```

Take the first hit as `since` and a point after the flow ended as `until`. A daemon log
under `~/agent/logs/` often brackets an operation too, but its timestamps may be the
container's local zone, not UTC; the `.jsonl` and `events.db` are UTC.

## Write the retrospective

The transcript is the evidence; the retrospective is the analysis on top. Read the whole
slice, then write a report that cites timestamps: outcome, a timeline table, what worked,
and findings (friction, bugs, doc gaps) each with its evidence line. Keep the raw
transcript as a companion file so each claim is checkable.

## Gotchas

- **`events.db` tool_end rows carry no output.** If you build a transcript from `events.db`
  alone, every tool result is missing and you will not notice, the rows exist, they are
  just empty of output. Use the `.jsonl`.
- **A pasted secret lands in three places.** A key the user typed into chat sits in the
  `.jsonl`, `events.db`, AND the chat store; the agent scrubbing one does not clear the
  others. The extractor redacts on the way out, so the transcript is safe to share even
  when the raw stores are not.
- **Shared host with live agents.** These are real users' agents. Read only; never write to
  a container's stores. A process listing can spill another agent's system prompt, do not
  paste container internals around.
- **The session slug is not fixed.** The `.jsonl` lives under a per-project slug directory
  (e.g. `-root-agent`); the driver globs for `<session_id>.jsonl` rather than assuming it.
- **Only the `[HH:MM:SS]` prefix is UTC.** That prefix is normalized; a timestamp *inside* a
  rendered payload (a channel `timestamp=` attribute, a daemon-log line) is verbatim and may
  carry the container's local offset, so do not read it as the window being wrong.

## Troubleshooting

- `no session transcript for <id>`: the agent compacted or restarted into a new session,
  so an old window may live in a rotated `.jsonl`. List them (the glob must run
  container-side): `sudo docker exec <container> sh -c 'ls -la /root/.claude/projects/*/'`.
- Empty output: the window matched nothing. Timestamps are UTC and string-compared, a
  local-zone `since` silently misses. Re-derive the window from `events.db`.
