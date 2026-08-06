A daemon's pid record is `<pid> <starttime>`, where the starttime is field 22 of
`/proc/<pid>/stat`. A pid alone answers "does some process hold this number", never "is this still
the process that was recorded", and a pid recycled inside one container lifetime otherwise reads as
a healthy daemon: `status` says running, the idempotent start declines, and the service is down with
its one health check reporting health it never measured.

Every skill that ships with your box already writes and reads that record. This migration brings the
skills you created yourself to the same contract, and fixes the empty log a detached Python child
leaves when its output stays block-buffered. Every step checks before acting and no-ops when
already converged, so it is safe to run more than once.

### 1. Find every local daemon and everything that reads its record

```bash
grep -rln 'daemons/.*\.pid\|PIDFILE\|pidfile' ~/agent/skills/ --include='*.py' --include='*.sh' --include='*.go' --include='*'
```

Two sets matter and they are not the same. **Writers** are the daemon lifecycles of skills you
created. **Readers** are anything that opens a pid record to decide whether something is alive: a
watchdog, a health check, a cron script, a line in your own notes that pipes the file to `kill`.
A reader you miss is worse than a writer you miss, so list both before changing anything.

### 2. Every reader takes the pid from the record's first field

This is the step that breaks things if it is skipped. A reader written as

```bash
kill -0 "$(cat "$PIDFILE")"
```

passes the whole record to `kill`, which fails on a perfectly healthy daemon. A watchdog built that
way restarts a working daemon on every tick; a health check built that way reports a dead daemon
that is running fine. Take the first field instead:

```bash
record="$(cat "$PIDFILE" 2>/dev/null)"
pid="${record%% *}"
[ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
```

In Python, `PIDFILE.read_text().split()[0]`. Fix every reader you listed in step 1, including your
own, before touching a writer.

### 3. Every writer records the starttime with the pid

Read the daemon contract in `~/agent/skills/vestad/SKILL.md` first, then follow the exemplar there
in your skill's own language. Each local skill keeps its own copy of the lifecycle: there is no
shared runner, and there is not meant to be one.

The starttime comes from `/proc/<pid>/stat`. Its `comm` field is bracketed and may itself contain
spaces and parentheses, so the numbered fields resume after the **last** `)`, not the first:

```bash
awk '{ for (i = NF; i > 0; i--) if ($i ~ /\)$/) { print $(i + 20); exit } }' "/proc/$pid/stat"
```

Write `<pid> <starttime>`, and a bare pid where `/proc` cannot answer, which is the honest form of
"identity unknown". Write the full record everywhere the pid is written, including the exclusive
claim a start takes before it spawns: a start killed between claiming and recording otherwise leaves
a record no reader can verify.

### 4. Compare a record against the process before trusting it

Where the lifecycle decides a daemon is alive, keep the `kill -0` check and add the comparison: if
the record carries a second field that is a plain run of digits, and the live process reports a
different starttime, the record is stale and the daemon is dead. A record with no second field is
one an older writer left, so trust it as before rather than reading a missing starttime as a
mismatch, or the daemon you are converting is declared dead while it is running and a second copy
stacks beside it. Any second field that is not a run of digits is treated the same way.

### 5. A detached Python child logs unbuffered

A daemon spawned as `Popen([...], stdout=log_handle, ...)` hands the child a file rather than a
terminal, so CPython block-buffers its output: the startup line sits in a 4KB buffer for hours and
the log reads as a dead daemon while the process works fine. The log is the liveness evidence
everyone reads, so this gets diagnosed as an outage that is not happening. Spawn Python children
with buffering off:

```python
subprocess.Popen([...], env={**os.environ, "PYTHONUNBUFFERED": "1"}, ...)
```

Only Python children need this; a compiled binary manages its own buffering, which is why the stock
voice skill does not set it.

### 6. Verify each converted daemon

```bash
<skill> daemon status
cat ~/agent/data/daemons/<name>.pid
```

Status must print one JSON line. A record written by the converted code carries two fields; one
still carrying a bare pid belongs to a daemon that has not restarted since the change, which is
correct and needs no action. Restart a daemon only if you were going to anyway.

If a local skill cannot be converted, leave it running, record what remains, tell the user, and
leave this migration unmarked so it retries later. Never stop a messaging, notification, or
user-facing daemon to finish this.

Commit your skill changes so the next upstream merge preserves them.

### 7. Mark this migration applied

Only when step 6 left nothing unconverted: call `mark_migration_applied` with
`name="2026-08-daemon-pid-starttime"`. If anything remains, stop here without marking, so the
migration retries on a later boot.
