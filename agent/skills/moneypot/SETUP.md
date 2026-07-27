# Moneypot setup

Put `moneypot` on PATH (idempotent, safe to re-run):

```bash
mkdir -p ~/.local/bin && ln -sf ~/agent/skills/moneypot/moneypot ~/.local/bin/moneypot
```

The **CLI then needs no further setup**: `moneypot ...` works immediately and creates `~/agent/data/moneypot.json` on first write.

The **HTTP API is optional**. To run it as a vestad-proxied service:

1. Start it:

   ```bash
   moneypot daemon start
   ```

   The service is private, so vestad authenticates every request before proxying it and the
   server itself needs no credential. Manage it with `daemon start|stop|restart|status`.

   **An external caller** gets its own service key, scoped to moneypot and revocable:

   ```bash
   KEY=$(service-key mint moneypot --label "budget app")
   ```

   The secret is printed once and never again, so hand it to the caller as you mint it. The
   caller sends it as `Authorization: Bearer <key>` or as `?token=<key>`. A key lasts 30 days
   unless you pass `--ttl <secs>` or `--never-expires`. List the live keys with
   `service-key list moneypot`, and revoke one with `service-key revoke moneypot <id>`.

2. Add this line yourself, inside the fenced block in the `## Daemons` section of
   `~/agent/skills/restart/SKILL.md`:

   ```
   running moneypot || { moneypot daemon start; sleep 1; }
   ```

3. Verify, with a key from step 1:

   ```bash
   curl -s "$VESTAD_TUNNEL/agents/$AGENT_NAME/moneypot/health?token=<key>"
   ```

   A request with no credential gets a 401 from vestad before the server ever sees it.

Stdlib only, no dependencies to install.
