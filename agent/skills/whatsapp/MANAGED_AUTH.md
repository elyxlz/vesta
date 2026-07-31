# WhatsApp service boundaries and authentication

Use this technical reference after selecting an operational setup guide:

- [SETUP_VESTA_CLOUD.md](SETUP_VESTA_CLOUD.md) for Vesta Cloud orchestration.
- [SETUP_DOUBLETICK.md](SETUP_DOUBLETICK.md) for the standalone Double Tick service.
- [SETUP_SELF_MANAGED.md](SETUP_SELF_MANAGED.md) when the user's phone stays the
  WhatsApp account.

A Double Tick service provides the WhatsApp account end to end. Vesta Cloud brokers
entitlement and authentication; the agent runs the companion. Account source and
API transport are independent decisions: never use “managed” or the presence of
credentials to infer both.

## Contents

- [Service boundaries](#service-boundaries)
- [Vesta Cloud route](#vesta-cloud-route)
- [Double Tick route](#double-tick-route)
- [Headless Double Tick account flow](#headless-double-tick-account-flow)
- [Failure ownership](#failure-ownership)
- [Persisted selection](#persisted-selection)

## Service boundaries

| Component | Owns | Does not own |
| --- | --- | --- |
| Double Tick | The headless WhatsApp account end to end (registration, sessions, companion pairing, WhatsApp health, and the account-bound residential proxy) | Tenant billing or entitlement |
| Vesta Cloud | Tenant authentication, entitlement, and brokering a hosted Double Tick WhatsApp account | WhatsApp sessions or the account-bound proxy |
| Agent | Companion session and local WhatsApp state | The headless WhatsApp account |

## Vesta Cloud route

1. The agent asks local vestad for a short-lived server-identity token.
2. It calls Vesta Cloud's WhatsApp route with that token.
3. Vesta Cloud verifies tenant entitlement and provisions a hosted Double Tick
   WhatsApp account.
4. Double Tick supplies the account's proxy lease and accepts companion pairing.

The agent holds no standing Double Tick secret. Vesta Cloud owns orchestration and
service credentials; it does not proxy the WhatsApp socket.

## Double Tick route

The agent calls `DOUBLETICK_API_URL` with:

```text
Authorization: Bearer wak_account-scoped-key
```

The `wak_` key authenticates only to the Double Tick service and never traverses
Vesta Cloud.

A `vesta.run` Cloudflare hostname can front a standalone Double Tick service
without making it a Vesta Cloud request path. Complete direct credentials take
precedence over cloud identity and must be set together:
`DOUBLETICK_API_URL` plus `DOUBLETICK_API_KEY`.

## Headless Double Tick account flow

Both Vesta Cloud and a standalone Double Tick service provide a ready headless
WhatsApp account:

1. The Double Tick service provisions or recovers the WhatsApp account.
2. Double Tick returns the residential proxy bound to that account.
3. The companion installs that proxy before generating its pairing code.
4. Double Tick accepts the pairing code and keeps the account session available.

The companion must use the bound Double Tick proxy on initial pairing and every
reconnect. This policy follows `primary_mode=doubletick`, not whether the API route
is cloud or direct. Fail closed when the lease is missing or invalid.

Do not allow an arbitrary `WHATSAPP_PROXY_URL` to replace the bound lease for a
Double Tick account. A user-supplied proxy is only meaningful for the user's own
phone, where no Double Tick account exists.

## Failure ownership

Keep failures with the service that owns the state:

- WhatsApp restricted, banned, logged out, or pairing failed: Double Tick.
- Tenant unauthorized: Vesta Cloud.
- Companion disconnected with a healthy account: agent/CLI.

When Double Tick reports a banned or unusable WhatsApp account, follow its `next`
for a fresh account; recovering the account is Double Tick's to handle.

## Persisted selection

Persist these independent facts per WhatsApp instance:

```text
primary_mode  = user | doubletick
api_transport = none | vesta_cloud | doubletick
```

Use `primary_mode` for proxy and reply-first policy, and `api_transport` for API
authentication and routing. Internal aliases remain implementation details; agents
invoke `whatsapp connect`.
