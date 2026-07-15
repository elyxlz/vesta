The WhatsApp daemon folded its many per-concern state files (managed-auth.json,
auth-status.json, last-exit.json, daemon-info.json, pairing-attempts.json, and the
linked-at marker) into a single `state.json` per instance under `~/.whatsapp/`. The
new daemon does the fold automatically on its next start (it reads the old files,
writes `state.json`, and deletes them; losslessly, and it keeps reading the old
files as a fallback until then), so there is nothing to hand-edit. This migration
just makes convergence happen promptly and confirms it. Safe to run more than once:
every step checks before acting and no-ops when already converged.

### 0. Skip if WhatsApp is not installed

If `~/agent/skills/whatsapp/SKILL.md` does not exist, there is nothing to do:
call `mark_migration_applied` with `name="2026-07-whatsapp-state-consolidation"` and STOP.

### 1. Let the daemon converge on its next natural restart

Do NOT restart the WhatsApp daemon just for this. Restarting inside the fragile
post-link history-sync window logs the device out, and the old daemon keeps working
fine until it next restarts on its own (a container restart or a deliberate
`whatsapp daemon restart` you were already doing). Whenever that next restart
happens, the new binary consolidates the files automatically.

If you run more than one instance (e.g. `whatsapp ... --instance personal`), each
instance's data dir converges the same way on its own next restart; nothing
instance-specific to do here.

### 2. Confirm the skill still answers

Run `whatsapp status`. A normal `linked`/`not linked` verdict means the CLI is
healthy against the new state layout. (If it reports `linked: false`, the one and
only recovery is still `whatsapp provision`, exactly as before; do that only with
the user's go-ahead, never in a retry loop.)

### 3. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-whatsapp-state-consolidation"`.
