Docker's tiny init now runs as PID 1 in this container and reaps orphaned skill daemons. Review
every skill that implements the daemon contract and remove any zombie-specific liveness workaround
added to compensate for an unreaped daemon.

Read `~/agent/skills/vestad/SKILL.md` and `~/agent/skills/skills-registry/SKILL.md` completely
before changing a skill. Keep the daemon contract intact.

Remove only logic whose sole purpose is to read `/proc/<pid>/stat`, detect process state `Z`, or
treat a zombie specially. Keep the ordinary PID existence probe (`kill -0` or `os.kill(pid, 0)`),
pid and port records, exclusive start claim, readiness check, bounded stop, JSON responses,
registration, logging, and notification behavior. Do not remove a check merely because it is named
`alive`; inspect what it does.

For each changed skill, run its daemon tests when it has them, then exercise:

```bash
<skill> daemon status
<skill> daemon restart <preserved flags>
<skill> daemon status
```

The restart must bring the daemon back and the final status must report it running. Preserve every
flag and setting. If one skill cannot be cleaned up safely, leave it unchanged, record what remains,
and continue with the others. Tell the user about anything left over and leave this migration
unmarked so it can retry later.

Commit any skill changes so the next upstream merge preserves them. If no skill contains a
zombie-specific workaround, there is nothing to change.
