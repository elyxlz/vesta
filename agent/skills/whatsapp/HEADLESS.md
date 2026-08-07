# WhatsApp headless proxy and failure ownership

The residential-proxy rule and failure boundaries shared by the two headless
methods ([Vesta Cloud](SETUP_VESTA_CLOUD.md), [Double Tick](SETUP_DOUBLETICK.md)).
The [SETUP.md](SETUP.md) flow selects the method and owns recovery.

## Residential proxy lease

Both headless methods bind a residential proxy to the WhatsApp account. The
companion must install that bound lease and use it on initial pairing and on every
reconnect. The proxy carries WhatsApp traffic only.

Fail closed: if the lease is missing or invalid, stop and report rather than
connecting over the datacenter IP or any other direct egress. Do not let a
user-supplied `WHATSAPP_PROXY_URL` replace the bound lease for a headless account;
a user-supplied proxy is meaningful only for a self-managed account.

## Failure ownership

Keep failures with the service that owns the state:

- WhatsApp restricted, banned, logged out, or pairing failed: Double Tick. Follow
  its `next` for a fresh account.
- 403 `membership_inactive`: Vesta Cloud, and specifically the billing side; the
  box's account holds no active paid membership. The fix is the membership
  (`vesta-cloud plan` / `manage`), never a re-link or a fresh account.
- Any other tenant-unauthorized response: Vesta Cloud.
- Companion disconnected with a healthy account: agent/CLI.
