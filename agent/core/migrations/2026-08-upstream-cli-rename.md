The upstream skill lives at `~/agent/skills/upstream/` and its command is `upstream`. The GitHub App private key normally moves with the sync; a dirty checkout can leave it at the old path, so step 1 moves it if needed. Every step reads disk state first, so this is safe to run more than once.

### 1. Move the App private key if it is still at the old path

```bash
OLD=~/agent/skills/upstream-pr/cli/src/upstream_pr_cli/private-key.pem
NEW=~/agent/skills/upstream/cli/src/upstream_cli/private-key.pem
[ -f "$OLD" ] && [ ! -f "$NEW" ] && mv "$OLD" "$NEW"; ls -la "$NEW"
```

The `ls` must show the key at the new path. If neither path has a key, continue: this box never set one up, and `upstream` will say so when first used.

### 2. Remove the stranded old directory

Only after step 1, and only if it still exists:

```bash
[ -d ~/agent/skills/upstream-pr ] && rm -rf ~/agent/skills/upstream-pr; ls ~/agent/skills/ | grep -c '^upstream-pr$' || true
```

The count must be 0.

### 2b. Install gh if the box does not have it

```bash
command -v gh >/dev/null || (apt-get update && apt-get install -y --no-install-recommends gh); gh --version | head -1
```

The last line must print a `gh version` line. `upstream gh` runs that binary, so if the install fails, STOP, leave this migration unmarked, and report it to the user.

### 3. Reinstall the command under its new name

```bash
uv tool uninstall upstream-pr 2>/dev/null; uv tool install --editable --force ~/agent/skills/upstream/cli
command -v upstream
```

The last line must print a path under `~/.local/bin`. If it does not, STOP and leave this migration unmarked.

### 3b. Drop the stale name from the active skill list

```bash
~/agent/skills/skills-registry/scripts/skills-deactivate upstream-pr
```

`upstream-pr` matches no skill directory, so that entry activates nothing. The script reads the list first and prints `Skill 'upstream-pr' is not active.` when the name is already absent, so this is safe to run more than once. `upstream` is a default skill and activates on every boot, so nothing has to be added.

### 4. Verify auth works, by exit status only

```bash
upstream token >/dev/null && echo auth-ok
```

Never run `token` bare: stdout persists into your event store. If this fails, the key may be missing or unreadable, or the GitHub API may be unreachable; report it to the user, but still complete step 5, since the steps above are done and an auth failure is separate from them.

### 5. Mark this migration applied

Call `mark_migration_applied` with this migration's name.
