# Managed WhatsApp auth (token strategy)

The `whatsapp` skill supports **two auth strategies**, auto-selected:

- **Self-hosted / user-QR (existing):** no token. The user links their own
  WhatsApp by scanning the QR (`SETUP.md`). The agent acts as the user.
- **Managed (this doc):** a redemption **token** is present. The agent redeems it
  against the [whatsapp-auth-api](https://github.com/elyxlz/vesta-cloud) and gets
  its **own** brand-new number, with no eSIM/QR/user effort.

Selection rule: **token in seed context → managed; else → self-hosted.**

## Model A (the agent runs its own whatsmeow)

The API never holds the agent's credentials. The agent:
1. `POST /redeem {token}` → `{session_id, agent_secret, msisdn, proxy, state}`.
   If `state == queued` (pool dry), poll `GET /sessions/{id}` until `msisdn` is
   bound (never rejected — that's the API's constraint #4).
2. `whatsmeow PairPhone(msisdn)` → an 8-char code. **`msisdn` is the assigned
   primary's number**; the agent links to it as a companion.
3. `POST /sessions/{id}/pair {code}` with header `X-Agent-Secret: <secret>` → the
   API drives the primary on its rooted phone to accept the link.
4. whatsmeow fires `PairSuccess` → authenticated. The agent now drives that
   WhatsApp account from its own whatsmeow.
5. Persist `{base, session_id, agent_secret, msisdn}` to
   `~/.whatsapp[/instance]/managed-auth.json`.

**Reauth** (companion dropped): `PairPhone(msisdn)` again → `POST
/sessions/{id}/pair` again (same endpoint; the birth token is not reused). One
cheap call, no new number, no OTP, no user action.

## CRITICAL: reply-first posture (anti-ban)

A 2026-06-29 live run proved the whole auth flow works mechanically (register,
auto-detect OTP, companion link, send) but the freshly-provisioned account was
**banned by WhatsApp within ~15 minutes**. The trigger was the maximum-risk
profile: a minutes-old number, a non-official multi-device client (whatsmeow,
which WhatsApp fingerprints), an **immediate cold message to a non-contact**, on a
rooted device. The blocker for managed WhatsApp is account trust, not the plumbing.

So the managed strategy MUST be reply-first:

1. **Never cold-initiate.** The agent must not send the first message in a thread
   to someone who has not messaged it. Onboarding delivers the agent's managed
   number to the user (seed context) with the instruction that **the user texts
   the agent first**; the agent only ever replies inside an established thread.
2. **Warm before use.** A freshly-provisioned number has near-zero trust; treat
   the first days as warm-up (light, human-paced, reply-only) before any volume.
3. **Prefer aged numbers** in the pool over fresh SIMs (a fresh SIM is itself a
   ban signal).

Wiring implication: `handleManagedAuth()` provisions + persists the number but
does NOT auto-send; the skill's send path guards against initiating a thread to a
non-contact. This refines GOAL #2 (the *first* message is inbound, then the agent
replies). See `whatsapp-auth-api/PROGRESS.md` for the full finding.

## Implemented + tested

`cli/managed_auth.go` — the HTTP client, on-disk state, and the handshake
orchestration: `redeem` (with queued-poll), `provision` (redeem → mint code via an
injected `pairPhone` → `link`), `reauth` (fresh code → re-link), `link`, `status`,
`save`/`loadManagedState`. `cli/managed_auth_test.go` covers all of it (redeem
immediate + queued→fulfilled, provision full handshake, reauth, link code+secret,
errors). Verified in isolation; the full CLI build needs the whisper.cpp headers
present in the agent image.

`pairPhone` is injected so the flow is testable without a live client; in the
daemon it is `wac.PairPhone`. So the Connect hook is a one-liner:
`st, err := wac.managed.provision(token, wac.PairPhone)` (or `loadManagedState` +
`reauth` on restart/drop).

## Wiring TODO (do in the agent build env / supervised)

1. `cli/cli.go::runServe` — read the token + API base from `--whatsapp-token` /
   `WHATSAPP_AUTH_TOKEN` + `--whatsapp-auth-api` / `WHATSAPP_AUTH_API` (or from
   `seed-context.md`). Pass to `NewWhatsAppClient`.
2. `cli/client.go` — add `managed *managedAuth` + `managedToken string` to
   `WhatsAppClient`. In `Connect()`, when `Store.ID == nil`: if a managed token
   (or a saved `managed-auth.json`) is present, run `handleManagedAuth()` instead
   of `go handleQRAuthentication()`.
3. `handleManagedAuth()`: `st := managed.redeem(token)` (or `loadManagedState`);
   `code, _ := wac.PairPhone(st.MSISDN)`; `managed.link(st, code)`; the existing
   `PairSuccess` event handler flips status to authenticated. On reconnect
   failure in `initiateReauth()`, if managed: `PairPhone` + `link` again.
4. `onboard` CLI (`onboard/cli/.../cli.py`): add `--whatsapp-token`, thread it +
   the user's number into `seed_context` so the born agent gets both. Seed context
   must also deliver the agent's managed number to the user with the **text-the-
   agent-first** instruction (reply-first posture above), so the first message is
   always inbound.
5. vesta-cloud control plane: mint exactly one token per paid account.
