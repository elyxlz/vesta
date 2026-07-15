# Managed WhatsApp auth (hosted strategy)

The `whatsapp` skill picks one of two auth strategies automatically:

- **Self-hosted (QR):** the user links their own WhatsApp by scanning the QR
  (`SETUP.md`). The agent acts as the user.
- **Managed (this doc):** a hosted (vesta.run) box gets its **own** number on
  demand, no eSIM, QR, or user effort.

Selection: **a hosted box with no linked WhatsApp uses managed; otherwise QR.**
Provisioning is **lazy and agent-initiated**: every paid account is entitled to
exactly one number, but a number is claimed only when the agent actually needs
WhatsApp (`whatsapp provision`). A user who never uses WhatsApp never gets one.

## How auth works

There is one pool API (on the home phone box) with three native paths, and two
interchangeable ways to reach it. The agent code (`cli/managed_auth.go`) picks by
environment; the paths and payloads are identical either way.

- **Cloud (vesta.run tenant):** the agent holds no WhatsApp secret. It mints a
  short-lived **server-identity token** from its own vestad (`POST
  https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/account-token`, `X-Agent-Token`
  authed; vestad signs it locally from the box `api_key`, no network call) and
  calls `https://vesta.run/api/whatsapp/*` with it as a Bearer. vesta.run is a
  **pure auth-forward**: it verifies the token + the paid-membership gate, then
  passes the request through to the home box verbatim, injecting our upstream key
  and the Vesta account id (`X-Vesta-Account`). `/api/whatsapp/<x>` maps 1:1 to the
  home box's `/<x>`, so vesta.run adds no API of its own.
- **Direct (self-hosted):** set `WHATSAPP_API_URL` (the home box base) and
  `WHATSAPP_API_KEY` (a per-account `wak_…` key the box operator minted). The agent
  calls the home box directly with `Authorization: Bearer <wak key>` — no vestad,
  no vesta.run. The home box derives the account from the key. Exactly the
  third-party-API-key model, pointed at our own box.

The home box owns all number/session state, keyed by that account id.

The flow:

1. Auth per the mode above (mint a token, or just use the direct key).
2. `POST /provision` → `{msisdn, state}`. Idempotent: the account's one number is
   returned as-is if it already has one. If the pool is dry the number is queued
   (empty `msisdn`); poll `GET /session` until it is bound (the pool never rejects).
3. `whatsmeow PairPhone(msisdn)` → an 8-char code (the agent links to the assigned
   primary as a companion).
4. `POST /pair {code}` → the home box drives the primary to accept the link.
5. whatsmeow fires `PairSuccess` → authenticated. The agent drives that account
   from its own whatsmeow, and persists `{msisdn}` to
   `~/.whatsapp[/instance]/managed-auth.json`.

**Reauth** (companion dropped): `PairPhone(msisdn)` again → `POST /pair` again. One
cheap call, no new number, no OTP, no user action.

## CRITICAL: reply-first posture (anti-ban)

A live run proved the flow works mechanically but a freshly-provisioned account
was **banned within ~15 minutes**. The trigger was the maximum-risk profile: a
minutes-old number, a non-official client (whatsmeow), and an **immediate cold
message to a non-contact**. The blocker for managed WhatsApp is account trust, not
the plumbing. So the managed strategy MUST be reply-first:

1. **Never cold-initiate.** Do not send the first message in a thread to someone
   who has not messaged first. Onboarding surfaces the agent's number with the
   instruction that **the user texts the agent first**; the agent only replies
   inside an established thread. `managedState.WaMeLink(text)` builds the
   `https://wa.me/<number>?text=...` link the agent surfaces for that.
2. **Warm before use.** Treat the first days as warm-up (light, human-paced,
   reply-only) before any volume.
3. **Prefer aged numbers** in the pool over fresh SIMs (a fresh SIM is itself a
   ban signal).

The `NewWhatsAppClient` fingerprint fix (`client.go`: `SetOSInfo` + Chrome
`PlatformType`) presents as Chrome-on-Linux instead of whatsmeow's giveaway
`Os="whatsmeow"` default. A lazy tell, cheap to close; behaviour still dominates.

## One command, terminal result (why the edge cases can't happen)

`whatsapp provision` is a top-level command (`runProvision`), built exactly like
`whatsapp link`: it cold-starts the daemon (`startDaemonProcess` waits for the
socket through the first-boot recompile, up to 5 min), then dispatches the
synchronous `provision` command, which runs the whole handshake **in the daemon**
and returns a terminal `{status:"linked", msisdn}` or a clear error. There is no
step for the agent to sequence, so the failure modes are gone by construction:

- **No recompile / daemon-readiness race:** the command blocks on the socket
  until the daemon answers, so it just waits out the compile instead of failing.
- **No websocket race:** the daemon-side handshake brings the pairing websocket up
  and `PairPhone` waits for it before generating a code.
- **No polling / silent async failure:** the call blocks until linked and returns
  the outcome; nothing to poll, nothing to lose.
- **No ban-guard burn:** managed pairing generates a code only once the websocket
  is up, and a failed pre-connection attempt records nothing (`checkPairAttempt`
  before, `recordPairAttempt` only on a generated code).
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
status), else `wac.linker.provision(wac)` brings the pairing WS up, claims the
number (or re-links a saved one), mints the code via `wac.PairPhone`, posts it, and
waits (`ManagedLinkTimeout`) for the companion to finish linking, returning the
state or a terminal error. On ANY failure it disconnects, leaving the client clean
for the next attempt (no GetQRChannel-on-connected-client error on retry).

`Connect()` never auto-pairs: a hosted box with no linked device stays idle until a
deliberate `whatsapp provision`. A logged-out device is never re-paired
automatically: the daemon records the logout, notifies the agent, clears the dead
device, and exits, so the next serve restarts into a fresh device for a deliberate
`whatsapp provision`. The persisted number (in `state.json`) means that re-provision
re-links the SAME number (reauth), no re-claim.

**Live validation still needed:** the phone-code pairing choreography over a
managed number is structurally faithful to the proven QR + `pair-phone` paths but
is not exercised by the unit tests (the CLI build needs the whisper headers).
`cli/managed_auth_test.go` covers the HTTP handshake, queued→bound, reauth, and
the error/missing-credential paths against a fake vestad + control plane;
`cli/linker_test.go` covers the paradigm selection, wrong-command rejection, and
direct-cred persistence.

The control plane (vesta-cloud) owns the paid-membership gate and the proxy to the
home box; the agent side is this client plus the Connect wiring above.
