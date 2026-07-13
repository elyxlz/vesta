---
name: claude-code
description: Delegate heavy coding tasks to Claude Code (Anthropic's autonomous coding CLI). Use for large multi-file refactors, building entire features or modules, complex debugging that needs extensive exploration, and substantial code reviews. For small edits, single-file changes, and quick fixes, use Vesta's own Read/Edit/Bash tools directly.
---

# Claude Code - CLI: `claude`

The `claude` CLI is a separate autonomous coding agent with a coding-tuned system prompt and the right default tools.

When you invoke it, shell out in print mode (`-p`). It runs to completion in one call and only the final result comes back, so Vesta's own context stays clean.

## When to use this skill

Reach for `claude` when the task is genuinely big:

- Building a whole feature or new module
- Multi-file refactors or "do this across the repo"
- Complex debugging that needs extensive exploration before a fix
- Substantial code reviews or security reviews of large diffs
- Anything that would otherwise burn many turns of Vesta's own loop reading and editing files

For everything smaller (single-file edits, quick fixes, typos, renames, reading code, small additions to existing functions), do it yourself with Read/Edit/Bash: the subprocess and autonomous-turn overhead exceeds Claude Code's value on modest work.

## Basic call

```bash
claude -p "<task>" \
  --output-format json \
  --max-turns 20 \
  --permission-mode bypassPermissions \
  --allowedTools "Read,Edit,Write,Bash,Grep,Glob"
```

JSON response shape:
```json
{
  "result": "<final text Claude Code returned>",
  "session_id": "75e2167f-...",
  "total_cost_usd": 0.078,
  "num_turns": 7,
  "subtype": "success"
}
```

Parse `result` and report it. Capture `session_id` for follow-ups.

Use a generous bash timeout when invoking it: coding work can take minutes, so set 5+ minute timeouts for non-trivial tasks. Pass the user's exact intent, not your paraphrase: Claude Code's prompt is tuned for natural-language coding tasks; don't pre-digest. And don't nest claude calls inside the task string: if the task itself involves running `claude`, you've over-decomposed; just describe the goal.

## Multi-turn (follow-ups)

Sessions live on Claude Code's side. No Vesta storage needed: the `session_id` is just a string you hold in conversation context and pass back.

```bash
# Turn 1: get session_id from the JSON
claude -p "Refactor auth module to use JWT" --output-format json --max-turns 20 ...

# Turn 2: continue the same session
claude -p "Now add tests" --resume <session_id> --output-format json --max-turns 10 ...

# Or continue the most-recent session in this cwd
claude -p "Anything you missed?" --continue --output-format json --max-turns 5 ...

# Fork: new id, keeps history
claude -p "Try a different approach" --resume <session_id> --fork-session ...
```

When the user follows up ("now also fix X"), reuse the previous `session_id` so Claude Code keeps full context. For an unrelated coding task, start fresh.

## Worktrees

For non-trivial coding work, run inside a git worktree. The user always wants new work isolated on its own branch.

```bash
cd /path/to/repo
git worktree add .claude/worktrees/<slug> -b <branch-name>
cd .claude/worktrees/<slug>
claude -p "<task>" --output-format json --max-turns 20 ...
```

Report the worktree path and branch back to the user along with the result.

## Useful flags

- `--allowedTools <list>` - comma-separated whitelist (`"Read,Edit,Bash"`). Scope to what the task needs.
- `--max-turns <n>` - cost cap; always set it. A confused subagent can otherwise loop indefinitely on your dollar. 5-10 for small tasks, 20-30 for refactors.
- `--max-budget-usd <n>` - dollar cap. Minimum ~$0.05.
- `--permission-mode bypassPermissions` - always use it. Without it the CLI prompts for permission and hangs forever in non-interactive mode.
- `--output-format json` - single result blob with metadata; always use it. You need `session_id` for follow-ups and `result` to report back; plain-text mode loses both.
- `--model sonnet | opus | haiku` - override default. `haiku` for cheap one-shots, `opus` for hard reasoning.
- `--add-dir <path>` - grant access to additional directories beyond `cwd`.
- `--append-system-prompt-file <path>` - add extra instructions on top of Claude Code's default prompt.
- `--continue` / `--resume <id>` - resume sessions (see above).
- `--fork-session` - branch off a session with a new id.
