# Personality Setup

## Wire the bubble lint (texting-brevity enforcement)

The "short bubbles, one thought per send" rule is easy to state and easy to regress on: a rule in the preset is something the agent must remember to enact on every message. `hooks/bubble_lint.py` enforces it at send time instead.

It's a `PreToolUse` hook on `Bash`: when a `telegram`/`whatsapp send` carries an inline `--message` that's a wall (over ~220 chars, or 2+ sentences crammed in one bubble), it exits 2, which blocks the call and feeds the reason back so the agent re-sends as several short calls. A command containing several `send` calls is linted per-send, and the error names the specific offender(s), so a batch of clean bubbles passes and only a flagged send needs re-splitting.

Genuine reference material (a morning brief, a code block, a requested list) bypasses with the `--longform` flag on the send command (e.g. `telegram send ... --message "..." --longform`). The flag is a real parsed CLI flag that lives OUTSIDE `--message`, so it can never leak into the delivered text. Loop/array sends and `--message-file` sends are already-split or reference, so they pass untouched.

Add this to `~/.claude/settings.json` under `hooks` (merge with any existing `PreToolUse` array, don't clobber other hooks):

```json
"PreToolUse": [
  {
    "matcher": "Bash",
    "hooks": [
      { "type": "command", "command": "python3 ~/agent/skills/personality/hooks/bubble_lint.py" }
    ]
  }
]
```

Hook config is read at session start, so it goes live on the next restart. The thresholds in `bubble_lint.py` (`MAX_CHARS`, `MAX_SENTENCES`) are tunable to how terse a given user's texting style is.
