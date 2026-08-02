# Vesta Cloud WhatsApp account

Vesta Cloud provisions a hosted, headless WhatsApp account and the agent links a
companion to it. Use this on a box whose account includes managed WhatsApp: today
that is a vesta.run managed VM (`vesta-cloud whoami` reports `account:true` with
`managed_infra:true`).

## Prerequisites

No key and no manual setup: the CLI authenticates with a short-lived credential
from `vesta-cloud token` on each call. The account must hold an active paid
membership; a 403 `membership_inactive` from the connect means it does not, and
the fix is the membership (see `vesta-cloud plan` / `manage`), not a re-link.

Run `whatsapp status` first; stop if linked or connecting.

## Connect

Compose a short, natural opener from the user's perspective, then run:

```bash
whatsapp connect --source vesta-cloud --opener 'Hi, it is me, nice to meet you here'
```

Vesta Cloud authenticates the tenant, provisions the hosted account, and pairs the
companion over the account's
[residential proxy lease](HEADLESS.md#residential-proxy-lease).
Reauthentication keeps the session binding; a fresh account is a new Vesta Cloud
provision.

Follow the returned `next`. Reply-first behavior is in [SKILL.md](SKILL.md);
recovery outcomes are in [SETUP.md](SETUP.md#status-and-recovery).
