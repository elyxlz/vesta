Normal upstream sync rebases stock's changes onto yours, and any stock change that
doesn't collide with a line you touched lands silently: you end up running the new
skills, prompts, and memory structure without ever having read the improvements. Worse,
edits you (or the user) committed long ago can sit on top of a file stock has since
improved, so the improvement never fully reached you and no diff ever put it in front
of you. This is a one-time, deliberate, deep review: look at the FULL difference between
your current state and the stock snapshot of the version you run, by hand, and
consciously absorb anything good you have been missing. Do NOT rebase or run the sync
scripts to "catch up" here: the whole point is that you read and decide, not that a tool
merges silently again.

Treat this as a serious block of work, not a quick chore. Dedicate real time to it and
go deep: every skill, every prompt, every hunk gets read and understood, not skimmed.
Because the divergence is broad, do not try to hold all of it in one context: fan out
with subagents. Spawn many of them, one per skill or per coherent area, so each reads
its slice of the diff thoroughly and in parallel, then bring their findings back and
apply the absorptions. Err on the side of more subagents and more depth: this migration
exists precisely because the fast pass the first time around missed things.

### 1. Get the stock snapshot for your version

```bash
cd ~
VERSION="$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
bash agent/core/skills/upstream-sync/scripts/fetch-upstream.sh
git rev-parse -q --verify "refs/tags/agent-v$VERSION" >/dev/null && echo ok || echo no-tag
```

- `ok`: continue.
- `no-tag` (or the fetch fails): Vesta's daemon has no snapshot for your version (an
  unconverted or unmanaged-core box). There is nothing to compare against here; mention
  it to the user and finish.

### 2. See the landscape

```bash
git diff --stat HEAD "agent-v$VERSION"
```

This is your entire divergence from stock. `agent/core/` is a read-only mount you cannot
edit and it already matches stock, so ignore any lines under it. What matters is
everything else: your installed skills (`agent/skills`, `agent/core/skills`),
`agent/MEMORY.md`, and any other file you or a past sync left changed.

### 3. Fan out and read the full diff in depth

From the `--stat`, carve your divergence into coherent areas: each installed skill under
`agent/skills` and `agent/core/skills` is its own area, `agent/MEMORY.md` is one, and
group whatever else remains. Spawn a subagent per area, as many as it takes to cover
everything, and run them in parallel. Give each subagent one instruction: read the full
patch for its paths, hunk by hunk, understand every change, and report back a precise
list of what to absorb (which stock improvements you are missing) versus what is your own
deliberate personalization to keep, with exact file paths and the reasoning per hunk.

Each subagent reads its slice like this (never just the stat):

```bash
git diff HEAD "agent-v$VERSION" -- <its paths>
```

Read this direction carefully: the patch transforms YOUR state into STOCK, so the `-`
lines are what you currently have and the `+` lines are stock's current version. For
every hunk, the subagent decides honestly which it is:

- **Stock improved this and you were sitting on an old copy** (a better script, a
  clearer instruction, a fixed command, a renamed file): take stock's version. Adopt the
  `+` side.
- **This is your own deliberate personalization** (a filled-in `[Fill in...]` stub, a
  note, a file you created, a rule you set up): keep it. Leave the `-` side as is.
- **A mix** (stock rewrote a file you had also personalized): take stock's new form and
  re-apply your specifics on top, so both survive. Never blanket-pick one side.

Once the subagents report back, do the absorbing yourself so the changes are applied from
one place, by editing the files directly. To lift stock's whole version of a file you
have no personal stake in:

```bash
git checkout "agent-v$VERSION" -- <path>    # stock still ships it: take stock's copy
git rm -r <path>                            # stock deleted it: drop yours too
```

Every hunk must be read and understood by some subagent: leave nothing skimmed. The
reason this migration exists is that a fast pass misses exactly the improvements you never
consciously saw the first time.

### 4. Commit and load

If you changed anything, commit it:

```bash
git -C ~ add -A && git -C ~ commit -m "manually absorb missed upstream changes"
```

Then, only after the final step below has marked this migration applied (so it does not
re-run on the way back up), call `restart_vesta` so any refreshed skills load. If you
absorbed nothing, no commit and no restart are needed.
