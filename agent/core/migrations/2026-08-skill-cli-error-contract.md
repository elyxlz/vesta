Audit every skill command created on this box against the command output contract, and converge
any that print failures on stdout or exit 0 on failure.

### 1. Read the contract, then list every locally created command

Read the section "Every skill command: the output contract" in `~/agent/skills/vestad/SKILL.md`
completely. In short: stdout carries only a command's successful output; a command that cannot do
its job exits non-zero and prints its failure on stderr, in the same shape it already prints (a
JSON `{"error": ...}` envelope or plain text); an exit code may itself be a documented answer for
a probe command, which is not a failure.

Then list every command belonging to a skill you created on this box: each console script a local
skill's `cli/` project installs, each `~/agent/skills/<skill>/<skill>` executable, and each helper
script another of your skills shells out to. Keep a checklist so every locally created command is
accounted for before marking the migration applied. Shipping skills are already conformant and are
not part of this migration.

### 2. Converge each command

For each command on the checklist, read how it prints and exits. A conformant command needs
nothing; auditing it again is a no-op. For each command that prints a failure on stdout, or exits
0 when it failed to do its job, change it so that:

- every failure prints on stderr and exits non-zero, keeping the same payload shape it printed
  before, so nothing that reads the message breaks
- stdout carries only successful output
- the stream choice runs through one helper per binary that decides by outcome, rather than a
  per-print choice at each site (the whatsapp CLI's `emit` in
  `~/agent/skills/whatsapp/cli/cli.go` is the Go shape; mirror the idea in the command's own
  language)
- an exit code documented as an answer (a "does X exist" probe) stays as it is

Then check your own scripts for the reverse dependency: any place one of your scripts runs
another command and greps that command's stdout for failure text now needs to read stderr or the
exit code instead. Fix those callers in the same pass.

### 3. Verify each changed command

For every command you changed, run one deliberately failing invocation (a missing required
argument, a nonexistent id) and confirm all three at once:

```bash
<command> <failing-args> >/tmp/out.txt 2>/tmp/err.txt; echo "exit=$?"
# exit is non-zero, /tmp/out.txt is empty, /tmp/err.txt carries the failure
```

Also run one normal invocation to confirm success output still lands on stdout. Commit the
changed skills so the next upstream merge preserves them.

### 4. Mark applied

If any command cannot be converged, record what remains in the affected skill's notes, tell the
user, and leave this migration unmarked so it retries on a later boot. Otherwise call
`mark_migration_applied` with `name="2026-08-skill-cli-error-contract"`.
