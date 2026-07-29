The email-client skill is a standard `cli/` uv project at `~/agent/skills/email-client/cli`. Its two
commands, `email-client` (read/manage IMAP + calendar) and `email-client-send` (SMTP), are
`[project.scripts]` console scripts installed with `uv tool install --editable` onto `~/.local/bin`,
the same shape as every other CLI skill. The poll daemon runs `email-client daemon start|stop|restart|status`
and records its pid under `~/agent/data/daemons/`. Your accounts, tokens, watermarks, and config stay
where they are, under `$EMAIL_CLIENT_DIR` (default `~/.email-client`); only the code lives in the project.

This migration installs the console scripts and clears the standalone code environment a box may still
carry. Every step no-ops when there is nothing to do, so it is safe to run more than once.

### 1. Skip if email-client was never set up

```bash
ls -d ~/.email-client
```

If that prints nothing, there is no email-client install to converge: go straight to step 5 and mark
this migration applied.

### 2. Install the console scripts

```bash
uv tool install --editable --force ~/agent/skills/email-client/cli
command -v email-client email-client-send
```

The second line must print two paths under `~/.local/bin`. If it does not, STOP, leave this migration
unmarked, and tell the user: without the console scripts your email commands and the poll daemon have
nothing to run.

### 3. Remove the old command wrappers

Earlier setup copied two bash wrappers into the system bin. Remove them so `email-client` resolves to
the console script rather than a wrapper pointing at code that has moved:

```bash
sudo rm -f /usr/local/bin/email-client /usr/local/bin/email-client-send 2>/dev/null || rm -f /usr/local/bin/email-client /usr/local/bin/email-client-send
```

### 4. Remove the standalone code environment

The commands now run from the project's own environment, so the separate runtime env and the module
symlinks beside your data are dead weight. This removes only code; your accounts, tokens, and config
are untouched:

```bash
rm -rf ~/.email-client/runtime
rm -f ~/.email-client/*.py
```

If a poll daemon is running, hand it to the new code so it stops running from the old environment:

```bash
[ -f ~/agent/data/daemons/email-client.pid ] && email-client daemon restart
email-client daemon status
```

Expect `{"running":true,"port":null}` when a daemon was running, or `{"running":false,"port":null}`
when none was.

### 5. Mark this migration applied

Call `mark_migration_applied` with `name="2026-08-email-client-cli"`.
