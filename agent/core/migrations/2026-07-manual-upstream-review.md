Normal upstream sync rebases stock's changes onto yours, and any stock change that
doesn't collide with a line you touched lands silently: you end up running the new
skills, prompts, and memory structure without ever having read the improvements. Worse,
edits you (or the user) committed long ago can sit on top of a file stock has since
improved, so the improvement never fully reached you and no diff ever put it in front
of you. This is a one-time, deliberate read: look at the FULL difference between your
current state and the stock snapshot of the version you run, by hand, and consciously
absorb anything good you have been missing. Do NOT rebase or run the sync scripts to
"catch up" here: the whole point is that you read and decide, not that a tool merges
silently again.

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

### 3. Read the full diff and absorb, file by file

Go through the actual patch, not just the stat, one area at a time, e.g.:

```bash
git diff HEAD "agent-v$VERSION" -- agent/skills agent/core/skills
git diff HEAD "agent-v$VERSION" -- agent/MEMORY.md
```

Read this direction carefully: the patch transforms YOUR state into STOCK, so the `-`
lines are what you currently have and the `+` lines are stock's current version. For
every hunk, decide honestly which it is:

- **Stock improved this and you were sitting on an old copy** (a better script, a
  clearer instruction, a fixed command, a renamed file): take stock's version. Adopt the
  `+` side.
- **This is your own deliberate personalization** (a filled-in `[Fill in...]` stub, a
  note, a file you created, a rule you set up): keep it. Leave the `-` side as is.
- **A mix** (stock rewrote a file you had also personalized): take stock's new form and
  re-apply your specifics on top, so both survive. Never blanket-pick one side.

Do the absorbing by editing the files directly. To lift stock's whole version of a file
you have no personal stake in:

```bash
git checkout "agent-v$VERSION" -- <path>    # stock still ships it: take stock's copy
git rm -r <path>                            # stock deleted it: drop yours too
```

Take your time and read every hunk. The reason this migration exists is that a fast skim
misses exactly the improvements you never consciously saw the first time.

### 4. Commit and load

If you changed anything, commit it:

```bash
git -C ~ add -A && git -C ~ commit -m "manually absorb missed upstream changes"
```

Then, only after the final step below has marked this migration applied (so it does not
re-run on the way back up), call `restart_vesta` so any refreshed skills load. If you
absorbed nothing, no commit and no restart are needed.
