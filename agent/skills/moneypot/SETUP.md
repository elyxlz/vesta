# Moneypot setup

The **CLI needs no setup**: `python3 ~/agent/skills/moneypot/moneypot.py ...` works immediately and creates `~/agent/data/moneypot.json` on first write.

The **HTTP API is optional**. To run it as a vestad-proxied service:

1. Start it:

   ```bash
   ~/agent/skills/moneypot/scripts/daemon start
   ```

   It registers a private port, which vestad proxies only to callers sending the vesta
   `AGENT_TOKEN`. Manage it with `daemon start|stop|restart|status`, never raw `screen`.

2. **Only if an external caller cannot send the agent token**, give that caller its own key.
   The key file is what makes the service public, so create it and then restart:

   ```bash
   install -m 600 /dev/null ~/agent/data/moneypot-api-key
   python3 -c "import secrets; print(secrets.token_urlsafe(24))" > ~/agent/data/moneypot-api-key
   ~/agent/skills/moneypot/scripts/daemon restart
   ```

   Callers then send `X-API-Key: <key>` (or `Authorization: Bearer <key>`).

3. Add this line yourself, inside the fenced block in the `## Daemons` section of
   `~/agent/skills/restart/SKILL.md`:

   ```
   running moneypot || { ~/agent/skills/moneypot/scripts/daemon start; sleep 1; }
   ```

4. Verify:

   ```bash
   curl -s "$VESTAD_TUNNEL/agents/$AGENT_NAME/moneypot/health"
   ```

Stdlib only, no dependencies to install.
