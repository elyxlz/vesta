The `service` skill grew into the `vestad` skill: one place for everything about talking
to vestad, the host daemon (service registration, public URLs, updating vestad, gateway
logs). The `register-service` helper moved with it, so any daemon line still calling the
old path would fail on the next boot. This migration repoints those lines, drops the old
skill, and trims the MEMORY.md sections the skill now owns. Safe to run more than once:
every step checks before acting and no-ops when already converged.

### 0. Wait for the vestad skill to exist

If `~/agent/skills/vestad/SKILL.md` does not exist yet, STOP HERE and do NOT call
`mark_migration_applied`: the upstream sync later this boot brings it, and this migration
re-runs on the next boot with the skill in place. Do not attempt the steps below without it.

### 1. Repoint register-service callers

Rewrite every occurrence of the old helper path to the new one in files you own
(most likely the `## Daemons` blocks of `~/agent/skills/restart/SKILL.md`, possibly
`~/.bashrc` or other personalized scripts):

```bash
grep -rl 'skills/service/scripts/register-service' ~/agent/skills/restart/ ~/.bashrc 2>/dev/null
```

In each hit, replace `skills/service/scripts/register-service` with
`skills/vestad/scripts/register-service`. If grep finds nothing, this step is done.

### 2. Drop the old `service` skill

```bash
~/agent/skills/skills-registry/scripts/skills-remove service
```

If it prints that `service` is not installed, there is nothing to do. If it errors because
the old directory holds uncommitted local changes, commit them
(`git -C ~ add agent/skills && git -C ~ commit -m "checkpoint skill edits"`) and run it again.

### 3. Trim MEMORY.md sections the vestad skill now owns

In `~/agent/MEMORY.md`, if a `### Service Registration` or `### Self-diagnosis` section
still exists under SYSTEM CONFIGURATION, replace both with this single section (keep any
personal notes you added there by moving them somewhere that fits):

```markdown
### vestad
- Everything about talking to vestad (registering services to get a port, public URLs, updating vestad, reading gateway logs) lives in the `vestad` skill (`~/agent/skills/vestad/SKILL.md`).
```

Also in `### Self-Modification`: if the config bullet still points at
`https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/config`, that endpoint is not reachable
with your token; replace the bullet with:

```markdown
- **Config (personality, timezone, notification rules)**: lives in your config store, edited through your own local API: `curl -s http://127.0.0.1:$WS_PORT/config -H "X-Agent-Token: $AGENT_TOKEN"` to read, PUT with the fields to change to write. **Model, context window, thinking** live on the provider: `curl -s -X PATCH http://127.0.0.1:$WS_PORT/provider -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' -d '{"model":"sonnet"}'`. Notification rules apply live; everything else applies on the next restart (`restart_vesta`). Other persistent env (skill secrets, PATH) still goes in `~/.bashrc` (`restart_vesta` to apply).
```

If the sections are already gone or already match, this step is done.

### 4. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-vestad-skill"`.
