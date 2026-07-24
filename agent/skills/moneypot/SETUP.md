# Moneypot setup

The **CLI needs no setup**: `python3 ~/agent/skills/moneypot/moneypot.py ...` works immediately and creates `~/agent/data/moneypot.json` on first write.

The **HTTP API is optional**. To run it as a vestad-proxied service:

1. Register a private port and start the server (uses the `vestad` skill):

   ```bash
   P=$(~/agent/skills/vestad/scripts/register-service moneypot) &&
   screen -dmS moneypot bash -c "cd ~/agent/skills/moneypot && PYTHONUNBUFFERED=1 python3 server.py --port $P > ~/agent/logs/moneypot.log 2>&1"
   ```

   The server automatically accepts the vesta `AGENT_TOKEN`, and vestad also
   requires that token before proxying a private service.

   **Public with a separate app key:** only use a public registration when an
   external caller cannot send the vesta agent token. Generate and store a key:

   ```bash
   KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
   install -m 600 /dev/null ~/agent/data/moneypot-api-key
   printf '%s\n' "$KEY" > ~/agent/data/moneypot-api-key
   P=$(~/agent/skills/vestad/scripts/register-service moneypot --public) &&
   screen -dmS moneypot bash -c 'cd ~/agent/skills/moneypot && PYTHONUNBUFFERED=1 python3 server.py --api-key "$(cat ~/agent/data/moneypot-api-key)" --port '"$P"' > ~/agent/logs/moneypot.log 2>&1'
   ```

   Callers then send `X-API-Key: <key>` (or `Authorization: Bearer <key>`).

2. Add the startup line to the `## Daemons` section of `~/agent/skills/restart/SKILL.md` so it comes back after a restart:

   ```bash
   running moneypot || { P=$(~/agent/skills/vestad/scripts/register-service moneypot) && screen -dmS moneypot bash -c "cd ~/agent/skills/moneypot && PYTHONUNBUFFERED=1 python3 server.py --port $P > ~/agent/logs/moneypot.log 2>&1"; sleep 1; }
   ```

3. Verify:

   ```bash
   curl -s "$VESTAD_TUNNEL/agents/$AGENT_NAME/moneypot/health"
   ```

Stdlib only, no dependencies to install.
