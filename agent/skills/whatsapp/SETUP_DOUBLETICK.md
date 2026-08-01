# Double Tick WhatsApp account

A standalone Double Tick service provides a dedicated, headless WhatsApp account
end to end. Requests go straight to Double Tick and never traverse Vesta Cloud.
Use this when a non-cloud agent points at such a service.

## Prerequisites

The operator provides the API base and one account-scoped key:

```bash
export DOUBLETICK_API_URL='https://doubletick.example'
export DOUBLETICK_API_KEY='wak_account-scoped-key'
```

Set both or neither, and keep the key out of chat, logs, commits, and command
output. The CLI persists valid credentials in the instance state so a later
environment scrub does not silently switch account methods. Auth detail (including
that a `vesta.run` hostname may front a standalone service) is in
[HEADLESS.md](HEADLESS.md).

Run `whatsapp status` first; stop if linked or connecting.

## Connect

Compose a short, natural opener from the user's perspective, then run:

```bash
whatsapp connect --opener 'Hi, it is me, nice to meet you here'
```

The CLI authenticates to Double Tick with the `wak_` key, provisions or recovers
the account, and pairs the companion over the account's
[residential proxy lease](HEADLESS.md#residential-proxy-lease).

Follow the returned `next`. Reply-first behavior is in [SKILL.md](SKILL.md);
recovery outcomes are in [SETUP.md](SETUP.md#status-and-recovery). Use the Double
Tick service's own status and logs for the account.
