# Moneypot setup

The **CLI needs no setup**: `moneypot ...` works immediately and creates `~/agent/data/moneypot.json` on first write. If the command is not on PATH yet, link it:

```bash
ln -sf ~/agent/skills/moneypot/moneypot ~/.local/bin/moneypot
```

The **HTTP API is optional**. It is a stdlib JSON server over the same pot data, for another app that needs to read or write pots over HTTP, and its lifecycle is a daemon owned by the CLI:

```bash
moneypot daemon start     # registers a private port with vestad, launches, returns once it answers
moneypot daemon status    # {"running":true,"port":NNNNN}
moneypot daemon stop
moneypot daemon restart
```

`start` is idempotent, so re-running it never stacks a second copy, and it returns only once the API actually answers on its port.

The port is registered **private**, so vestad is the gate in front of it and the API itself checks no credential. Reach it at `$VESTAD_TUNNEL/agents/$AGENT_NAME/moneypot/...` with the app api key, or mint a service key for a caller that holds no app credential:

```bash
service-key mint moneypot --label "what it is for"     # prints the secret once; share the keyed link
```

Register the startup line for restart as `~/agent/skills/restart/SKILL.md` describes, so the API comes back after a restart. It is the bare command, nothing around it, because start is idempotent:

```bash
moneypot daemon start
```

Verify:

```bash
curl -s "http://localhost:$(cat ~/agent/data/daemons/moneypot.port)/health"
```

Stdlib only, no dependencies to install.
