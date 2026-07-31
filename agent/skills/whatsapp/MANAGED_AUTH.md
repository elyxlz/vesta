# WhatsApp authentication and proxy

Auth boundaries and the proxy rule for the two headless methods
([Vesta Cloud](SETUP_VESTA_CLOUD.md), [Double Tick](SETUP_DOUBLETICK.md)). The
[SETUP.md](SETUP.md) flow selects the method and owns recovery.

Account source and API transport are independent decisions: never infer both from
the word "managed" or from the presence of credentials.

## Auth

**Vesta Cloud route.** The agent holds no standing Double Tick secret. It asks
local vestad for a short-lived server-identity token and calls Vesta Cloud's
WhatsApp route with it; Vesta Cloud verifies tenant entitlement and provisions a
hosted Double Tick account. Vesta Cloud carries API traffic only, never the
WhatsApp socket.

**Double Tick route.** The agent calls `DOUBLETICK_API_URL` directly with
`Authorization: Bearer $DOUBLETICK_API_KEY` (a `wak_` account-scoped key that
never traverses Vesta Cloud). Set `DOUBLETICK_API_URL` and `DOUBLETICK_API_KEY`
together or not at all; complete direct credentials take precedence over cloud
identity. A `vesta.run` hostname may front a standalone Double Tick service over a
Cloudflare tunnel without making it a Vesta Cloud request path.

## Residential proxy lease

Both headless methods bind a residential proxy to the WhatsApp account. The
companion must install that bound lease and use it on initial pairing and on every
reconnect. The proxy carries WhatsApp traffic only; API requests use the Vesta
Cloud or direct route above.

Fail closed: if the lease is missing or invalid, stop and report rather than
connecting over the datacenter IP or any other direct egress. Do not let a
user-supplied `WHATSAPP_PROXY_URL` replace the bound lease for a headless account;
a user-supplied proxy is meaningful only for a self-managed account, where no
Double Tick account exists.

## Failure ownership

Keep failures with the service that owns the state:

- WhatsApp restricted, banned, logged out, or pairing failed: Double Tick. Follow
  its `next` for a fresh account.
- Tenant unauthorized: Vesta Cloud.
- Companion disconnected with a healthy account: agent/CLI.
