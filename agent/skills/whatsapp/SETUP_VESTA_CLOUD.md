# Vesta Cloud WhatsApp account

Use this method for a Vesta Cloud tenant that needs a dedicated WhatsApp account
without keeping a user phone as the primary. Vesta Cloud provisions a hosted
WhatsApp account for the agent to link a companion to. The agent is a companion.

## Prerequisites

Cloud provisioning supplies `VESTA_CLOUD_CONTROL_URL`, the agent identity, and
vestad connectivity. Do not add Double Tick credentials to the agent: it mints
short-lived Vesta server-identity tokens, while the control plane holds the
service credentials.

Run `whatsapp status` first. Stop if linked or already connecting.

## Connect

Compose a short, natural opener from the user's perspective, then run:

```bash
whatsapp connect --opener 'Hi, it is me, nice to meet you here'
```

Vesta Cloud performs one flow:

1. Authenticate the tenant using a short-lived token minted by local vestad.
2. Verify tenant entitlement and provision the hosted Double Tick WhatsApp account.
3. Obtain Double Tick's residential proxy lease bound to that WhatsApp account.
4. Install the proxy on the companion, pair the companion with the hosted account,
   and wait for a terminal result.

Vesta Cloud carries API traffic, not the WhatsApp websocket. WhatsApp traffic uses
Double Tick's bound residential proxy on initial pairing and every reconnect. If
the lease is missing or invalid, stop rather than connect from the cloud VM's
datacenter IP.

## First contact

The account is dedicated to the agent and reply-first. Follow the returned `next`:
share the returned `wa.me` link, wait for an inbound message, then reply. Keep the
first days light and human-paced.

## Recovery

- `provisioning`: wait for the stated delay and repeat the command once.
- `blocked`: Double Tick found the WhatsApp account unusable. Follow `next` for a
  fresh account.
- `rate_limited`: wait out the named cooldown; do not retry-loop.
- Logged out after a prior link: obtain approval, then run the same command once.

Reauthentication keeps the Double Tick session binding. A fresh account is a new
Vesta Cloud provision.
Service and token details are in [MANAGED_AUTH.md](MANAGED_AUTH.md).
