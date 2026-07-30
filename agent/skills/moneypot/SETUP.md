# Moneypot setup

The **CLI needs no setup**: `moneypot ...` works immediately and creates `~/agent/data/moneypot.json` on first write. If the command is not on PATH yet, link it:

```bash
ln -sf ~/agent/skills/moneypot/moneypot ~/.local/bin/moneypot
```

The **HTTP API is optional**. It is a stdlib JSON server over the same pot data, for a dashboard or another app, and its lifecycle is a daemon owned by the CLI:

```bash
moneypot daemon start     # registers a private port with vestad, launches, returns once it answers
moneypot daemon status    # {"running":true,"port":NNNNN}
moneypot daemon stop
moneypot daemon restart
```

`start` is idempotent, so re-running it never stacks a second copy, and it returns only once the API actually answers on its port. The port is registered **private**, which is what you want: the API is read with the app credential (the dashboard sends `Authorization: Bearer $AGENT_TOKEN` for you), and anyone else is handed a minted service key rather than an open URL.

To hand the API to a caller that holds no app credential:

```bash
service-key mint moneypot     # prints a one-time secret; share the keyed link
```

**Optional extra app key.** Set `MONEYPOT_API_KEY` in `~/.bashrc` to require your own key on every route except `/health`. The agent token keeps working alongside it, so a dashboard is unaffected:

```bash
echo "export MONEYPOT_API_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" >> ~/.bashrc
```

Callers then send `X-API-Key: <key>` (or `Authorization: Bearer <key>`).

Add the startup line to the `## Daemons` section of `~/agent/skills/restart/SKILL.md` so the API comes back after a restart. It is the bare command, nothing around it, because start is idempotent:

```bash
moneypot daemon start
```

Verify:

```bash
curl -s "http://localhost:$(cat ~/agent/data/daemons/moneypot.port)/health"
```

Stdlib only, no dependencies to install.
