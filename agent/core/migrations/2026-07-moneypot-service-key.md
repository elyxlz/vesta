Your moneypot API server verifies nothing: it registers as a private vestad service, and
vestad authenticates every request before proxying it. So its startup line takes no key, and
an external caller reaches it with a service key vestad mints. This migration converges your
restart skill's moneypot line, its vestad registration, and the leftover key file. Every step
checks before acting and no-ops when already converged, so it is safe to run more than once.

### 0. Skip if the moneypot API is not set up

The moneypot CLI needs no setup and is unaffected; only the optional HTTP API is:

```bash
grep -n 'moneypot' ~/agent/skills/restart/SKILL.md 2>/dev/null
ls -l ~/agent/data/moneypot-api-key 2>/dev/null
```

If both come back empty (no moneypot daemon line and no key file), there is nothing to do:
call `mark_migration_applied` with `name="2026-07-moneypot-service-key"` and STOP.

### 1. Check the moneypot daemon line

`moneypot daemon start` registers the service privately and passes the server no key, so the
line in the `## Daemons` section of `~/agent/skills/restart/SKILL.md` needs nothing beyond that
launch:

```
moneypot daemon start
```

If the line already reads that way, this step is done: the `2026-08-daemon-pidfile` migration's
"Reduce every restart line to its command" step owns the whole Daemons block and runs after this
one in the same batch. If the line still spells out `server.py`, leave it: that step converts it,
or tells you to stop because your workspace sync has not merged, in which case both are converted
on your next boot.

### 2. Register moneypot privately now

Registration is idempotent and always sends the exposure explicitly, so this returns the same
port and makes the service private without waiting for a restart:

```bash
register-service moneypot
```

### 3. Delete the leftover key file

```bash
rm -f ~/agent/data/moneypot-api-key
```

### 4. Give any external caller a service key

If an app outside this box calls the moneypot API, it needs a service key, which is scoped to
moneypot and revocable. Mint one over the loopback with your own agent token, the same channel
`register-service` uses:

```bash
curl -sk -X POST https://$BOX_HOST:$VESTAD_PORT/agents/$AGENT_NAME/services/moneypot/keys \
  -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' \
  -d '{"label": "external caller"}'
```

The reply carries `id`, `key`, and `expires_at`. The `key` is shown this once only, so hand it
straight to the caller, which sends it as `Authorization: Bearer <key>` or as `?token=<key>`. A
key lasts 30 days unless the body asks for `{"ttl_secs": 604800}` or `{"never_expires": true}`,
so pass `never_expires` for a caller you do not want to re-key. A `GET` on that same URL lists
the live keys, and `curl -sk -X DELETE .../services/moneypot/keys/<id>` with the same header
revokes one.

Once your workspace sync has merged, `service-key mint moneypot` is the helper that does this
same call and prints the key alone.

Your server picks up the converged line at its next start, so if a caller needs its key working
right away, bring the daemon back with `moneypot daemon restart` once your workspace sync has
merged.
Tell the user which caller you re-keyed, and never paste a key into a chat you would not paste
a password into.

### 5. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-moneypot-service-key"`.
