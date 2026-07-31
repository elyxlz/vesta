# Vesta Cloud-managed WhatsApp number

Use this method for a Vesta Cloud tenant that needs a dedicated WhatsApp number
without keeping a user phone as the primary. Vesta Cloud coordinates two separate
services:

- **Vesta Switchboard** reserves the number, relays its verification SMS, and
  releases it; a replacement is a release plus a fresh reserve.
- **Double Tick** registers and operates the headless WhatsApp primary, accepts
  companion pairing, reports WhatsApp health, and supplies its bound proxy.

The agent is a companion. Double Tick never owns Switchboard's number inventory,
and Switchboard never owns a WhatsApp session.

## Prerequisites

Cloud provisioning supplies `VESTA_CLOUD_CONTROL_URL`, the agent identity, and
vestad connectivity. Do not add Double Tick or Switchboard credentials to the
agent: it mints short-lived Vesta server-identity tokens, while the control plane
holds the service-to-service credentials.

Run `whatsapp status` first. Stop if linked or already connecting.

## Connect

Compose a short, natural opener from the user's perspective, then run:

```bash
whatsapp connect --opener 'Hi, it is me—nice to meet you here'
```

Vesta Cloud performs one coordinated flow:

1. Authenticate the tenant using a short-lived token minted by local vestad.
2. Ask Switchboard for an opaque number lease for that tenant.
3. Give the lease reference to Double Tick; Double Tick obtains the number and
   verification SMS through its service integration and registers WhatsApp.
4. Obtain Double Tick's residential proxy lease bound to that WhatsApp primary.
5. Install the proxy on the companion, pair it with the headless primary, and
   wait for a terminal result.

Vesta Cloud carries orchestration/API traffic, not the WhatsApp websocket.
WhatsApp traffic uses Double Tick's bound residential proxy on initial pairing
and every reconnect. If the lease is missing or invalid, stop rather than connect
from the cloud VM's datacenter IP.

## First contact

The number is dedicated to the agent and reply-first. Follow the returned `next`:
share the number and prefilled `wa.me` link, wait for an inbound message, then
reply. Keep the first days light and human-paced.

## Recovery

- `provisioning`: wait for the stated delay and repeat the command once.
- `blocked`: Double Tick found the WhatsApp account unusable. Follow `next` so
  Vesta Cloud releases the lease and reserves a fresh number; Double Tick must not
  allocate one itself.
- `rate_limited`: wait out the named cooldown; do not retry-loop.
- Logged out after a prior link: obtain approval, then run the same command once.

Reauthentication keeps the Double Tick session binding. A fresh number is a new
Vesta Cloud reserve, never a Double Tick action.
Service and token details are in [MANAGED_AUTH.md](MANAGED_AUTH.md).
