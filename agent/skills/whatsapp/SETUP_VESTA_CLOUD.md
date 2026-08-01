# Vesta Cloud WhatsApp account

Vesta Cloud provisions a hosted, headless WhatsApp account and the agent links a
companion to it. Use this for a Vesta Cloud tenant that wants a dedicated account
rather than a self-managed one.

## Prerequisites

Cloud provisioning supplies `VESTA_CLOUD_CONTROL_URL`, the agent identity, and
vestad connectivity. Do not add Double Tick credentials: the agent mints
short-lived Vesta server-identity tokens and the control plane holds the service
credentials (see [HEADLESS.md](HEADLESS.md)).

Run `whatsapp status` first; stop if linked or connecting.

## Connect

Compose a short, natural opener from the user's perspective, then run:

```bash
whatsapp connect --source cloud --opener 'Hi, it is me, nice to meet you here'
```

Vesta Cloud authenticates the tenant, provisions the hosted account, and pairs the
companion over the account's
[residential proxy lease](HEADLESS.md#residential-proxy-lease).
Reauthentication keeps the session binding; a fresh account is a new Vesta Cloud
provision.

Follow the returned `next`. Reply-first behavior is in [SKILL.md](SKILL.md);
recovery outcomes are in [SETUP.md](SETUP.md#status-and-recovery).
