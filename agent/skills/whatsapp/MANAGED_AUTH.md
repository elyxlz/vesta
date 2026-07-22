# Managed WhatsApp auth (hosted strategy)

The `whatsapp` skill picks one of two auth strategies automatically:

- **Self-hosted (QR):** the user links their own WhatsApp by scanning the QR
  (`SETUP.md`). The agent acts as the user.
- **Managed (this doc):** a hosted (vesta.run) box gets its **own** number on
  demand, no eSIM, QR, or user effort.

Selection: **a hosted box with no linked WhatsApp uses managed; otherwise QR.**
Provisioning is **lazy and agent-initiated**: every paid account is entitled to
exactly one number, but a number is claimed only when the agent actually needs
WhatsApp (`whatsapp connect`). A user who never uses WhatsApp never gets one.

## How auth works

There is one pool API (on the home phone box) with two native paths (`/provision`,
`/pair`), and two interchangeable ways to reach it. The agent code
(`cli/managed_auth.go`) picks by environment; the paths and payloads are identical
either way.

- **Cloud (vesta.run tenant):** the agent holds no WhatsApp secret. It mints a
  short-lived **server-identity token** from its own vestad (`POST
  https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/account-token`, `X-Agent-Token`
  authed; vestad signs it locally from the box `api_key`, no network call) and
  calls `https://vesta.run/api/integrations/whatsapp/*` with it as a Bearer. vesta.run is a
  **pure auth-forward**: it verifies the token + the paid-membership gate, then
  passes the request through to the home box verbatim, injecting our upstream key
  and the Vesta account id (`X-Vesta-Account`). `/api/integrations/whatsapp/<x>` maps 1:1 to the
  home box's `/<x>`, so vesta.run adds no API of its own.
- **Direct (self-hosted):** set `DOUBLETICK_API_URL` (the doubletick base) and
  `DOUBLETICK_API_KEY` (a per-account `wak_…` key the box operator minted). The agent
  calls the home box directly with `Authorization: Bearer <wak key>`, no vestad,
  no vesta.run. The home box derives the account from the key. Exactly the
  third-party-API-key model, pointed at our own box.

The home box owns all number/session state, keyed by that account id.

**Egress selection (all modes):** set `WHATSAPP_PROXY_URL` to a full
`http(s)://` or `socks5://` URL (with optional `user:pass@`) to route the
companion's WhatsApp egress through your own proxy. Selection precedence is the
explicit override, then a doubletick lease, then direct egress. The CLI checks the
selected exit with ip-api.com before WhatsApp connects. If you're managed or on a
datacenter IP, the skill leases a residential proxy from doubletick automatically;
it hardfails rather than run WhatsApp over a datacenter IP. A supplied or leased
proxy that still classifies as hosting/non-residential also hardfails. ip-api's
`hosting` signal is the hard datacenter check; `mobile` is residential-safe, and
a non-hosting fixed-line exit is inferred to be residential.

The lease call is `POST {DOUBLETICK_API_URL}/proxy/lease`, authenticated exactly
like `/provision`. Cloud mode also sends `X-Vesta-Account`; direct/self-hosted mode
does not. Its response is `{"proxy_url":"http://user:pass@host:port","kind":"residential"}`.

The flow:

1. Auth per the mode above (mint a token, or just use the direct key).
2. `POST /provision` → `200 {msisdn}` once a number is bound. Idempotent: the
   account's one number is returned as-is if it already has one. A dry pool answers
   `409` with no ready account; re-POST the same idempotent `/provision` until it
   binds. There is no `GET /session`. A ban is a typed `403 account_banned` and a
   temporary restriction a `409 account_restricted` (never a 200 body); a ban means
   the number is unusable and re-running claims a fresh one, a restriction self-clears
   so waiting is the fix.
3. `whatsmeow PairPhone(msisdn)` → an 8-char code (the agent links to the assigned
   primary as a companion).
4. `POST /pair {code}` → the home box drives the primary to accept the link.
5. whatsmeow fires `PairSuccess` → authenticated. The agent drives that account
   from its own whatsmeow, and persists `{msisdn}` to the consolidated
   `~/.whatsapp[/instance]/state.json`.

**Reauth** (companion dropped): re-POST the idempotent `/provision` first, then
`PairPhone(msisdn)` → `POST /pair` again. Re-consulting `/provision` is what lets a
post-link ban recover: the control plane auto-heals a banned account onto a FRESH
number, so reauth pairs whatever `/provision` returns (usually the same number, no
OTP and no user action, but a healed new number when the old one was banned) and
surfaces `blocked` if the account is still healing.

## CRITICAL: reply-first posture (anti-ban)

A live run proved the flow works mechanically but a freshly-provisioned account
was **banned within ~15 minutes**. The trigger was the maximum-risk profile: a
minutes-old number, a non-official client (whatsmeow), and an **immediate cold
message to a non-contact**. The blocker for managed WhatsApp is account trust, not
the plumbing. So the managed strategy MUST be reply-first:

1. **Never cold-initiate.** Do not send the first message in a thread to someone
   who has not messaged first. Onboarding surfaces the agent's number with the
   instruction that **the user texts the agent first**; the agent only replies
   inside an established thread. Compose the opener yourself from your own name and
   personality: a warm, natural first-contact greeting that says hi and introduces
   you by name. Pass it with `whatsapp connect --opener '<text>'`.
   `waMeLink(number, text)` builds the `https://wa.me/<number>?text=...` link. The
   message is prefilled into the user's compose box and is what the USER sends TO
   the agent, so keep that reaching-out perspective. If `--opener` is empty, the
   existing generic greeting remains as a fallback.
2. **Warm before use.** Treat the first days as warm-up (light, human-paced,
   reply-only) before any volume.
3. **Prefer aged numbers** in the pool over fresh SIMs (a fresh SIM is itself a
   ban signal).

The `NewWhatsAppClient` fingerprint fix (`client.go`: `SetOSInfo` + Chrome
`PlatformType`) presents as Chrome-on-Linux instead of whatsmeow's giveaway
`Os="whatsmeow"` default. A lazy tell, cheap to close; behaviour still dominates.

## One command, terminal result (why the edge cases can't happen)

`whatsapp connect` is the single setup verb (`runConnect`). It picks the paradigm
the way `chooseLinker` does (managed pooled number vs. the user's own WhatsApp by
QR); the hidden `provision`/`link` aliases route to the same path. On a hosted box
it dispatches the managed arm (`runProvision`): cold-start the daemon
(`startDaemonProcess` waits for the socket through the first-boot recompile, up to 5
min), then dispatch the synchronous `provision` command, which runs the whole
handshake **in the daemon** and returns a terminal `{status:"linked", number,
next}` (or `{status:"provisioning"}` while the pool fills, `{status:"blocked"}` for
a banned number). Every output carries a `next:` step. There is no step for the
agent to sequence, so the failure modes are gone by construction:

- **No recompile / daemon-readiness race:** the command blocks on the socket
  until the daemon answers, so it just waits out the compile instead of failing.
- **No websocket race:** the daemon-side handshake brings the pairing websocket up
  and `PairPhone` waits for it before generating a code.
- **No polling / silent async failure:** the call blocks until linked and returns
  the outcome; nothing to poll, nothing to lose.
- **No ban-guard burn:** every managed `PairPhone` runs through the same
  ban-avoidance rate-limit guard as the phone path (`guardedPairPhone` in
  `linker.go`): `checkPairAttempt` BEFORE minting a code (a blocked cap returns a
  clean `{status:"rate_limited"}` and never pairs), and `recordPairAttempt` only on
  a generated code, so a re-run on a number that keeps failing to link cannot issue
  unbounded real pairing requests and a failed pre-connection attempt records nothing.
- **Idempotent:** already linked returns the number; a stuck run is safe to repeat.

## Wiring

The box picks ONE linker at construction: `chooseLinker` (`linker.go`) returns a
`managedLinker` when the box can reach a pool (a direct `wak_` key, or the vesta.run
server-identity path), else a `qrLinker`. The daemon never branches on mode inline
again; `managedLinker` holds the `managedAuth` HTTP client (which hides the
three-credential selection) and the state store (which owns the persisted number).

`cmdProvisionManaged` (the daemon-side `provision` handler) is synchronous and
single-flighted (`beginPairing`): an idempotent short-circuit if the device is
already linked (gated on `Store.ID`, the linked fact, not transient connection
status), else `wac.linker.provision(wac)` brings the pairing WS up, re-consults the
idempotent `/provision` to get the account's current number (a fresh one if the old
was banned), mints the code via the rate-limit-guarded `wac.PairPhone`, posts it,
and waits (`ManagedLinkTimeout`) for the companion to finish linking, returning the
state or a terminal error (`rate_limited`/`blocked`/`provisioning` become clean
statuses). On ANY failure it disconnects, leaving the client clean for the next
attempt (no GetQRChannel-on-connected-client error on retry).

`Connect()` never auto-pairs: a hosted box with no linked device stays idle until a
deliberate `whatsapp connect`. A logged-out device is never re-paired
automatically: the daemon records the logout, notifies the agent, clears the dead
device, and exits, so the next serve restarts into a fresh device for a deliberate
`whatsapp connect`. That connect re-consults `/provision`: normally it re-links the
SAME persisted number (`state.json`), but if that number was banned the control
plane hands back a fresh one and connect links that instead, so a post-link ban
recovers rather than looping on the dead number.

**Live validation still needed:** the phone-code pairing choreography over a
managed number is structurally faithful to the proven QR + `pair-phone` paths but
is not exercised by the unit tests (the CLI build needs the whisper headers).
`cli/managed_auth_test.go` covers the HTTP handshake, queued→bound, reauth, a
post-link ban surfacing `errBlocked`, a healed fresh number, and the
error/missing-credential paths against a fake vestad + control plane;
`cli/linker_test.go` covers the paradigm selection, wrong-command rejection,
direct-cred persistence, and the managed rate-limit guard (blocks at the cap
without pairing, records only on a generated code).

The control plane (vesta-cloud) owns the paid-membership gate and the proxy to the
home box; the agent side is this client plus the Connect wiring above.
