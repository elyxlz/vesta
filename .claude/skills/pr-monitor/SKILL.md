---
name: pr-monitor
description: >
  Use when the user asks to watch PRs, monitor GitHub, respond to PR comments as
  they arrive, keep an eye on review feedback, or run "pr-monitor". Starts a
  long-running event source that surfaces developer comments addressing
  @vestabot on open PRs, plus newly opened dependabot PRs, and keeps surfacing
  them until the session stops. Read-only on its own: it reports events, and
  acting on them is the session's job.
---

# PR Monitor

A background loop that watches open PRs and prints one line per new event. Pair it with the `Monitor` tool so a session is woken when something needs attention, instead of polling by hand.

## What it emits

```
HIT     <repo> <kind> <id> <pr> <url>    a developer comment addressing the bot
DEPPR   <repo> <pr> <url>                a newly seen open dependabot PR
```

`kind` is `issue` (PR conversation comment), `review` (inline review comment), or `reviewbody` (review summary).

## Getting running

1. **Check auth.** `gh auth status` must show an account with write access to the repos being watched. The loop posts reactions, so a read-only token is not enough.

2. **Start the loop under the Monitor tool**, pointing it at this skill's `monitor.sh`. With no arguments it watches the current repo; pass `owner/repo` arguments to watch several:

   ```bash
   .claude/skills/pr-monitor/monitor.sh
   .claude/skills/pr-monitor/monitor.sh elyxlz/vesta elyxlz/vesta-cloud
   ```

   Register that command as a Monitor event source. Each printed line becomes an event delivered to the session.

3. **Act on each event.** A `HIT` means a developer addressed the bot on that PR: read the comment at the URL, do what it asks, and reply on the PR. A `DEPPR` is a new dependabot PR, handled by whatever dependency policy is in force.

The loop keeps running until the session stops. Nothing survives the session: restarting it is safe and cheap, because dedup state lives on GitHub rather than on disk.

## Only comments that address the bot

A comment is surfaced only when its body mentions `@vestabot`. Everything else on the PR is ignored, so developers can talk to each other freely without waking an agent. Override the mention with `PR_MONITOR_TRIGGER`.

Dependabot PRs deliberately bypass this rule, since nobody is going to write a comment on one.

## How events are deduplicated

A surfaced item gets a 👀 reaction on the comment (or on the PR itself, for dependabot). The next cycle sees that reaction and skips it. That state lives on GitHub, so it survives losing the working directory, a reboot, or a move to another machine.

The reaction is posted at emit time, not by whatever handles the event. Without that, an item would re-fire every cycle for as long as it sat unhandled. The ack is also posted *before* the line is printed: if it fails, nothing is emitted and the item is retried next cycle, so a failure can never produce an event that gets handled twice.

Two consequences worth knowing:

- **Anyone's 👀 counts.** The check reads the reaction count, not who left it. A human reacting 👀 to a comment hides it from the loop. Removing the reaction surfaces it again.
- **Review summaries are the exception.** GitHub has no reactions endpoint for PR review summaries, so that one kind falls back to a small file under `PR_MONITOR_STATE`. Losing that file re-surfaces past review summaries.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `PR_MONITOR_TRIGGER` | `@vestabot` | Mention that makes a comment an event |
| `PR_MONITOR_INTERVAL` | `45` | Seconds between polls |
| `PR_MONITOR_STATE` | `$XDG_STATE_HOME/pr-monitor` | Where the review-summary ledger lives |

## Cost

One `gh pr list` per repo per cycle, plus three API calls per open PR. The trigger match and the reaction count are both read out of those same list payloads inside the jq expression, so neither adds a call. Only acking an event costs an extra request. At the default interval a repo with a handful of open PRs sits far under the 5000 per hour limit; a repo with many open PRs wants a longer `PR_MONITOR_INTERVAL`.
