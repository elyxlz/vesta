# WhatsApp service boundaries and authentication

Use this technical reference after selecting an operational setup guide:

- [SETUP_VESTA_CLOUD.md](SETUP_VESTA_CLOUD.md) for Vesta Cloud orchestration.
- [SETUP_DOUBLETICK_DIRECT.md](SETUP_DOUBLETICK_DIRECT.md) for direct Double Tick.
- [SETUP_SELF_MANAGED.md](SETUP_SELF_MANAGED.md) when the user's phone remains
  the WhatsApp primary.

Account topology, number source, and API transport are independent decisions.
Never use “pool,” “managed,” or the presence of credentials to infer all three.

## Contents

- [Service ownership](#service-ownership)
- [Vesta Cloud route](#vesta-cloud-route)
- [Direct Double Tick route](#direct-double-tick-route)
- [Headless Double Tick flow](#headless-double-tick-flow)
- [Switchboard-assisted self-managed flow](#switchboard-assisted-self-managed-flow)
- [Failure ownership](#failure-ownership)
- [Persisted selection](#persisted-selection)

## Service ownership

| Component | Owns | Does not own |
| --- | --- | --- |
| Vesta Switchboard | Number/SIM inventory, tenant number leases, SMS/OTP delivery, and the lease lifecycle (reserve a number, relay its OTP, release it; a replacement is a release plus a fresh reserve) | WhatsApp registration, sessions, pairing, or proxies |
| Double Tick | Headless WhatsApp primary sessions, registration state, companion pairing, WhatsApp health, and the primary-bound residential proxy | Number inventory, tenant billing, or number replacement policy |
| Vesta Cloud | Tenant authentication, entitlement, orchestration, and the mapping between a Switchboard lease and a Double Tick WhatsApp account | Number/SIM inventory or WhatsApp sessions |
| Agent | Companion session and local WhatsApp state | The headless primary or carrier-number lifecycle |

Connect services using an opaque `number_lease_id`. Do not share provider
credentials with Double Tick clients or treat an E.164 string as proof of lease
ownership.

## Vesta Cloud route

1. The agent asks local vestad for a short-lived server-identity token.
2. It calls Vesta Cloud's WhatsApp orchestration route with that token.
3. Vesta Cloud verifies tenant entitlement and obtains or recovers the tenant's
   Switchboard number lease.
4. Vesta Cloud gives the lease reference to Double Tick. Service-to-service
   integration lets Double Tick obtain the number and verification SMS without
   acquiring Switchboard credentials from the agent.
5. Double Tick provisions the WhatsApp primary, supplies its proxy lease, and
   accepts companion pairing.

The agent holds no standing Switchboard or Double Tick secret. Vesta Cloud owns
only orchestration and service credentials; it does not proxy the WhatsApp socket.

## Direct Double Tick route

The agent calls `DOUBLETICK_API_URL` with:

```text
Authorization: Bearer wak_account-scoped-key
```

The `wak_` key authenticates only to Double Tick. The Double Tick operator must
separately configure a number-service integration or number-lease reference for
the account. Direct mode never grants access to Switchboard implicitly and never
traverses Vesta Cloud.

A `vesta.run` Cloudflare hostname can expose a standalone Double Tick service
without making it a Vesta Cloud request path. Complete direct credentials take
precedence over cloud identity and must be set together:
`DOUBLETICK_API_URL` plus `DOUBLETICK_API_KEY`.

## Headless Double Tick flow

Both Vesta Cloud and direct Double Tick can operate a headless primary:

1. The responsible orchestrator obtains a number lease from its number service.
   Vesta Cloud uses Switchboard; a direct operator may configure another provider.
2. Double Tick provisions or recovers WhatsApp using that lease and the provider's
   verification channel.
3. Double Tick returns the residential proxy bound to the WhatsApp primary.
4. The companion installs that proxy before generating its pairing code.
5. Double Tick accepts the pairing code and keeps the primary session available.

The companion must use the bound Double Tick proxy on initial pairing and every
reconnect. This policy follows `primary_mode=doubletick`, not whether the API route
is cloud or direct. Fail closed when the lease is missing or invalid.

Do not allow an arbitrary `WHATSAPP_PROXY_URL` to replace the bound lease for a
Double Tick primary. A user-supplied proxy is only meaningful for self-managed
accounts, where no Double Tick primary exists.

## Failure ownership

Keep failures with the service that owns the state:

- Number unavailable, expired, or SMS unavailable: Switchboard/number service.
- WhatsApp restricted, banned, logged out, or pairing failed: Double Tick.
- Tenant unauthorized or services disagree about their mapping: Vesta Cloud.
- Companion disconnected with a healthy primary: agent/CLI.

When Double Tick reports a banned or unusable WhatsApp account, it returns the
failure and `number_lease_id`. The orchestrator decides what the number service
does with the lease: in v1 it releases it, and a replacement is a release followed
by a fresh reserve. Double Tick must never silently consume another number.

## Persisted selection

Persist these independent facts per WhatsApp instance:

```text
primary_mode = user | doubletick
number_source = user | switchboard | external
api_transport = none | vesta_cloud | doubletick_direct
number_lease_id = <opaque provider reference, when applicable>
```

Use `primary_mode` for proxy and reply-first policy, `number_source` for SMS and
lifecycle recovery, and `api_transport` only for API authentication/routing.
Hidden internal aliases remain implementation details; agents invoke
`whatsapp connect`.
