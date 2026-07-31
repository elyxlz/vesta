# Direct Double Tick-managed WhatsApp number

Use this method when a non-cloud or self-hosted agent calls a standalone Double
Tick service for a dedicated headless WhatsApp primary. Requests go straight to
Double Tick and never traverse Vesta Cloud.

Double Tick does not own phone-number inventory. Its operator must integrate a
separate number service that supplies number leases and verification SMS. That
provider may be Switchboard only when the operator has separately arranged access;
the agent's Double Tick key does not grant Switchboard access.

## Prerequisites

The Double Tick operator must provide one account-scoped key and the API base:

```bash
export DOUBLETICK_API_URL='https://doubletick.example'
export DOUBLETICK_API_KEY='wak_account-scoped-key'
```

Set both or neither. Keep the key out of chat, logs, commits, and command output.
The CLI persists valid direct credentials in the instance state so a later
environment scrub does not silently switch account methods.

Before handing out the key, the operator must configure that Double Tick account
with a number-service integration or an existing number-lease reference. Do not
put the number provider's credentials on the agent.

The API hostname may be a Cloudflare tunnel into the Double Tick box. A hostname
under `vesta.run` does not imply Vesta Cloud forwarding: the request path remains
agent → tunnel → standalone Double Tick.

## Connect

Compose a short, natural opener from the user's perspective, then run:

```bash
whatsapp connect --opener 'Hi, it is me—nice to meet you here'
```

The CLI performs one synchronous flow:

1. Authenticate directly to Double Tick with the `wak_` key.
2. Ask Double Tick to provision or recover the WhatsApp primary. Double Tick uses
   its configured number-service lease; it does not allocate inventory itself.
3. Obtain the residential proxy lease bound to that WhatsApp primary and install
   it on the companion before connecting.
4. Generate a companion pairing code and ask Double Tick to accept it.
5. Wait for the companion to report linked and return a terminal status.

Double Tick API calls go directly to `DOUBLETICK_API_URL`. The proxy carries only
WhatsApp traffic and is mandatory on initial pairing and every reconnect. Never
fall back to unrelated direct egress.

## First contact

The number is dedicated to the agent and reply-first. Follow the returned `next`:
share the number and prefilled `wa.me` link, wait for the user to message the
agent, then reply. Do not send a cold first message.

## Recovery

- `provisioning`: wait for the stated delay and repeat the same command once.
- `blocked`: Double Tick reports the WhatsApp failure and the number-lease
  reference. The operator/orchestrator decides whether its number service should
  quarantine, retain, or replace that lease; Double Tick must not silently allocate.
- `rate_limited`: wait out the exact cooldown; never generate extra pair codes.
- Logged out after a prior link: obtain approval, then repeat the same command once.

Use `whatsapp status` for the companion and the Double Tick operator's status/logs
for the primary. Service boundaries are in [MANAGED_AUTH.md](MANAGED_AUTH.md).
