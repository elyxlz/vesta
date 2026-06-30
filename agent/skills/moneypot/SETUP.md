# Moneypot setup

The **CLI needs no setup**: `python3 ~/agent/skills/moneypot/moneypot.py ...` works immediately and creates `~/.moneypot/data.json` on first write.

The **HTTP API is optional**. To run it as a vestad-proxied service:

1. Register a port and start the server (uses the `service` skill):

   ```bash
   P=$(~/agent/skills/service/scripts/register-service moneypot --public)
   screen -dmS moneypot bash -c "cd ~/agent/skills/moneypot && PYTHONUNBUFFERED=1 python3 server.py --port $P > ~/agent/logs/moneypot.log 2>&1"
   ```

   Drop `--public` for a token-gated service (reachable only with `X-Agent-Token`).

2. Add the startup line to the `## Daemons` section of `~/agent/skills/restart/SKILL.md` so it comes back after a restart:

   ```bash
   running moneypot || { P=$(~/agent/skills/service/scripts/register-service moneypot --public); screen -dmS moneypot bash -c "cd ~/agent/skills/moneypot && PYTHONUNBUFFERED=1 python3 server.py --port $P > ~/agent/logs/moneypot.log 2>&1"; sleep 1; }
   ```

3. Verify:

   ```bash
   curl -s "$VESTAD_TUNNEL/agents/$AGENT_NAME/moneypot/health"
   ```

Stdlib only, no dependencies to install.
