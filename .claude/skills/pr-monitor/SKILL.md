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
NEWPR   <repo> <pr> <url>                a newly seen open PR, for its first check
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

## Running unattended

`dispatch.sh` runs the loop without a supervising session: it reads the event stream and hands each event to `claude` in print mode, so it can be supervised by systemd instead of a terminal.

```bash
.claude/skills/pr-monitor/dispatch.sh elyxlz/vesta elyxlz/vesta-cloud
```

**One session per PR.** The session id from a PR's first event is stored under `PR_MONITOR_STATE` and resumed for every later event on that PR, so the agent remembers what it already pushed and tried there. Different PRs never share context. Losing that file costs continuity on the next event, never correctness.

Do not reach for `claude --from-pr` here. It resumes a session already linked to a PR, but a print-mode run does not create that link, so in a service it quietly starts a fresh session every time.

Events on different PRs run at the same time, up to `PR_MONITOR_PARALLEL`. Events on one PR do not: they resume that PR's session, and two runs resuming one conversation would interleave their writes, so a per-PR lock keeps them in single file. An event arriving while its PR is busy is left unclaimed rather than queued behind the run, so it comes back on a later cycle instead of resuming a session out from under whoever holds it.

Each run can build a worktree of several hundred megabytes, so the ceiling is disk as much as cost.

A run is also capped at `PR_MONITOR_TIMEOUT` and stopped past it. A run whose connection dies waits on a socket that never speaks again, consuming no CPU and looking alive from outside, and without the cap it holds its slot for as long as the process lives.

**Every new PR is checked automatically.** A non-draft PR that has never been seen surfaces as `NEWPR` without anyone asking, and dispatch runs the `check-pr` skill on it: does it fix the issue it claims to fix, does it match this repository's conventions, does it actually work. That pass is read only. It never pushes, merges, or closes, so a PR opening cannot cause a write. Where the change would benefit from the simplify and tidy pass, the reply names `polish-pr` and stops there, leaving the maintainer to ask for it.

An unprompted comment closes by saying how to reach the agent: that mentioning `@vestabot` on the PR is what triggers it, what is worth asking for, and that only trusted commenters can. Nobody asked for that comment, so it carries its own instructions rather than assuming the reader knows the loop exists. Replies to an explicit mention skip it, since whoever wrote the mention already knows.

**Seed before switching this on.** "Never seen" means "carries no 👀", so the first cycle treats every open PR as new and checks all of them at once. On a repo with a dozen open PRs that is a dozen agent runs back to back. Mark the existing ones first:

```bash
for n in $(gh pr list --repo owner/name --state open --json number -q '.[].number'); do
  gh api -X POST "/repos/owner/name/issues/$n/reactions" -f content=eyes >/dev/null
done
```

**The agent knows it is a reviewer.** Each comment event carries standing context ahead of the request itself: read the issue the PR claims to fix and judge whether it actually resolves it, check the change against this repository's own rules rather than generic taste (CLAUDE.md, the language conventions, any skill covering the area), and verify claims by reading the code and running things rather than trusting the description. That review happens whether or not the comment asked for one, so a bare mention still gets a real review instead of an ad-hoc answer.

**Every reply ends with a verdict.** The agent closes each comment with a line reading `Verdict: MERGE`, `DO NOT MERGE`, or `NOT YET`, plus one sentence of reasoning, so a maintainer scanning the PR list gets a recommendation rather than a wall of findings. The agent never merges or closes anything: the verdict is advice and the decision stays with whoever is watching. It is told to judge the change on its merits even when it wrote the code itself, and to say `DO NOT MERGE` when it means it.

**Sessions are closed out when their PR closes.** A PR's session is only ever resumed while the PR is open, so once it closes the pointer is dead weight. Dispatch prunes those pointers at startup and after each event. Session transcripts under `~/.claude/projects/` are the part that actually grows, so removing them is opt-in via `PR_MONITOR_PRUNE_TRANSCRIPTS=1` rather than silent, since they are also the only record of what the agent did. Leave it off and transcripts accumulate; watch the disk on a busy repo.

A long-lived PR is the one case still unbounded: every event resumes and extends the same session, so a PR with many rounds of review grows a large transcript and a large context. Nothing caps that today.

A systemd user unit, needing `loginctl enable-linger <user>` so it runs without a login:

```ini
[Unit]
Description=PR monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/pr-monitor
ExecStart=%h/pr-monitor/.claude/skills/pr-monitor/dispatch.sh elyxlz/vesta
Restart=always
RestartSec=30

[Install]
WantedBy=default.target
```

Point `WorkingDirectory` at a checkout kept for the service rather than a working one, so the code cannot change under a running loop.

## Only comments that address the bot

A comment is surfaced only when its body mentions `@vestabot`. Everything else on the PR is ignored, so developers can talk to each other freely without waking an agent. Override the mention with `PR_MONITOR_TRIGGER`.

Dependabot PRs deliberately bypass this rule, since nobody is going to write a comment on one.

## Only from people you trust

Anyone with a GitHub account can comment on a public repository's PRs, and a comment reaching this loop drives an agent that holds your credentials and can write to the repo. So the mention alone is never enough: the commenter must be trusted.

Set `PR_MONITOR_TRUSTED` to a list of logins and only those people can drive the agent:

```bash
PR_MONITOR_TRUSTED="alice,bob"
```

With it unset, trust falls back to the commenter's `author_association`, accepting `OWNER`, `MEMBER`, and `COLLABORATOR`. That is a reasonable default for a private repo, but on a public one prefer the explicit list, since the fallback trusts every collaborator rather than the specific people you meant.

An untrusted comment gets a 😕 (`PR_MONITOR_DENIED_REACTION`) instead of silence, so the person can see it was read and declined, and the loop stops reconsidering it. Review summaries cannot be marked this way, having no reactions endpoint, so those are recorded in the ledger and ignored.

The trust list is the whole gate, and it carries real authority. A trusted commenter can tell the agent to do things the repository's conventions otherwise discourage, a force push or a rebase for instance, and the agent will comply and say so in its reply. That is deliberate: the people on the list are maintainers who know when an exception is warranted, and asking them to work around their own agent would only push them back to doing it by hand.

Keep the list to people you would let push to the branch yourself.

## The agent must not wake itself

Every comment the agent posts ends with `<!-- vestabot:reply -->`, which renders as nothing, and any comment carrying it is skipped. That marker is the only thing separating the agent's writing from a human's: its comments name the trigger when telling a reader how to reach it, and it posts under an account that also belongs to a maintainer, so neither the body nor the author distinguishes them. Without the marker its own comment reads as a fresh request and it wakes itself on the next poll, once per cycle, forever.

The marker is written by the agent, so it holds only while the agent follows instructions. A separate bot identity would make it structural instead: comments from `<name>[bot]` are already skipped by author, needing nothing from the model. Override the string with `PR_MONITOR_MARKER`.

## How events are deduplicated

A surfaced item gets a 👀 reaction on the comment (or on the PR itself, for dependabot). The next cycle sees that reaction and skips it. That state lives on GitHub, so it survives losing the working directory, a reboot, or a move to another machine.

The reaction is posted at emit time, not by whatever handles the event. Without that, an item would re-fire every cycle for as long as it sat unhandled. The ack is also posted *before* the line is printed: if it fails, nothing is emitted and the item is retried next cycle, so a failure can never produce an event that gets handled twice.

The reaction is therefore a **claim, not a completion**. Under `dispatch.sh` a failed run releases the claim, removing only this account's reaction, and the event surfaces again on the next cycle. That is what makes a usage limit recoverable: the runs fail, the claims are released, and the events come back once the limit resets. A consumer that emits events some other way should release claims the same way, or a failure will drop the event silently.

Two consequences worth knowing:

- **Anyone's 👀 counts.** The check reads the reaction count, not who left it. A human reacting 👀 to a comment hides it from the loop. Removing the reaction surfaces it again.
- **Review summaries are the exception.** GitHub has no reactions endpoint for PR review summaries, so that one kind falls back to a small file under `PR_MONITOR_STATE`. Losing that file re-surfaces past review summaries.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `PR_MONITOR_TRIGGER` | `@vestabot` | Mention that makes a comment an event |
| `PR_MONITOR_TRUSTED` | (author_association) | Logins allowed to drive the agent |
| `PR_MONITOR_DENIED_REACTION` | `confused` | Reaction marking a refused comment |
| `PR_MONITOR_MARKER` | `vestabot:reply` | Marker identifying the agent's own comments |
| `PR_MONITOR_INTERVAL` | `45` | Seconds between polls |
| `PR_MONITOR_STATE` | `$XDG_STATE_HOME/pr-monitor` | Review-summary ledger and per-PR session ids |
| `PR_MONITOR_MODEL` | `claude-opus-5` | Model `dispatch.sh` runs each event on |
| `PR_MONITOR_TIMEOUT` | `1800` | Seconds a single run may take before it is stopped |
| `PR_MONITOR_PARALLEL` | `3` | Runs allowed at once, across different PRs |
| `PR_MONITOR_PRUNE_TRANSCRIPTS` | `0` | Delete a closed PR session transcript, not just its pointer |

## Cost

One `gh pr list` per repo per cycle, plus three API calls per open PR. The trigger match and the reaction count are both read out of those same list payloads inside the jq expression, so neither adds a call. Only acking an event costs an extra request. At the default interval a repo with a handful of open PRs sits far under the 5000 per hour limit; a repo with many open PRs wants a longer `PR_MONITOR_INTERVAL`.
