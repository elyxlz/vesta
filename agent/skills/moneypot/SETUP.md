# Moneypot setup

The **CLI needs no setup**: `python3 ~/agent/skills/moneypot/moneypot.py ...` works immediately and creates `~/agent/data/moneypot.json` on first write.

The **HTTP API is optional**. To run it as a vestad-proxied service:

1. Register a private port and start the server (uses the `vestad` skill):

   ```bash
   P=$(~/agent/skills/vestad/scripts/register-service moneypot) &&
   screen -dmS moneypot bash -c "cd ~/agent/skills/moneypot && PYTHONUNBUFFERED=1 python3 server.py --port $P > ~/agent/logs/moneypot.log 2>&1"
   ```

   The service is private, so vestad authenticates every request before proxying it and the
   server itself needs no credential.

   **An external caller** gets its own service key, scoped to moneypot and revocable:

   ```bash
   curl -sk -X POST https://$BOX_HOST:$VESTAD_PORT/agents/$AGENT_NAME/services/moneypot/keys \
     -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' \
     -d '{"label": "budget app"}'
   ```

   The reply is `{"id": ..., "key": ..., "expires_at": ...}`, and `key` is shown this once
   only. The caller sends it as `Authorization: Bearer <key>` or as `?token=<key>`. A key
   lasts 30 days unless the body asks for `{"ttl_secs": 604800}` or
   `{"never_expires": true}`. List the live keys with a `GET` on that same URL, and revoke
   one with `curl -sk -X DELETE .../services/moneypot/keys/<id>` plus the same header.

2. Add the startup line to the `## Daemons` section of `~/agent/skills/restart/SKILL.md` so it comes back after a restart:

   ```bash
   running moneypot || { P=$(~/agent/skills/vestad/scripts/register-service moneypot) && screen -dmS moneypot bash -c "cd ~/agent/skills/moneypot && PYTHONUNBUFFERED=1 python3 server.py --port $P > ~/agent/logs/moneypot.log 2>&1"; sleep 1; }
   ```

3. Verify, with a key from step 1:

   ```bash
   curl -s "$VESTAD_TUNNEL/agents/$AGENT_NAME/moneypot/health?token=<key>"
   ```

   A request with no credential gets a 401 from vestad before the server ever sees it.

Stdlib only, no dependencies to install.
