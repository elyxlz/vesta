The writing skill at `~/agent/skills/writing` handles every writing job. An `active_skills` list in `~/agent/data/config.json` may still contain `essay-iter`, a name that matches no skill directory, so that entry activates nothing. Re-point it. Safe to run more than once: each step reads the current state first.

### 1. Check whether there is anything to migrate

```bash
python3 -m json.tool ~/agent/data/config.json | sed -n '/"active_skills"/,/]/p'
```

If `essay-iter` is not in the list, there is nothing to migrate; go to step 3.

### 2. Swap the entry

```bash
~/agent/skills/skills-registry/scripts/skills-activate writing
~/agent/skills/skills-registry/scripts/skills-deactivate essay-iter
```

The change takes effect at the next restart, as any activation does.

### 3. Mark this migration applied

Call `mark_migration_applied` with `name="2026-08-essay-iter-to-writing"`.
