---
name: otp
description: Use when you need a one-time SMS verification code on a temporary phone number to sign up for or verify a service (a phone-number signup, an SMS 2FA step, a "we texted you a code" screen). Reserves a throwaway number, waits for the texted code, then releases the number. For WhatsApp, use the `whatsapp` skill instead.
---

# otp (CLI: `otp`)

Get a one-time SMS code on a temporary number, use it to clear a service's phone
verification, then give the number back. Three verbs run in order:

1. `otp new --service <name>` reserves a number and returns its `id`.
2. Enter that number as the phone number on the service you are verifying.
3. `otp code --id <id>` waits for the code the service texts, and prints it.
4. `otp release --id <id>` returns the number to the pool once you are done.

Every command prints JSON. The number is temporary and shared back to a pool, so
release it as soon as the code is used. Do not reuse an `id` for a second service.

## new: reserve a number

```bash
otp new --service github
otp new --service coinbase --country US
```

`--service` is required (the service you are verifying, for pool accounting).
`--country` is an optional ISO code when the service needs a specific region.
`--idempotency-key` is optional: if a `new` call fails transiently and you retry it,
pass the same key both times so the retry returns the same number instead of drawing
(and charging for) a second. Use a fresh key for each genuinely new signup.

Success prints the number to type into the service and the `id` to poll with:

```json
{ "number": "+15550001111", "id": "lease_abc123" }
```

Two outcomes are not errors to retry blindly:

- `{ "error": "otp_quota_exceeded", "next": "..." }`: the account's OTP allowance
  is spent. Wait for it to reset. Do not retry in a loop.
- `{ "error": "out_of_stock", "next": "..." }`: no number is free right now. Retry
  shortly, or pass a different `--country`.

## code: wait for the SMS

```bash
otp code --id lease_abc123
otp code --id lease_abc123 --since 2026-07-31T18:00:00Z
```

`otp code` polls until the code lands or a bounded timeout, then prints:

```json
{ "code": "482913" }
```

If the SMS has not arrived within the timeout, it prints a pending status instead
of failing. Trigger the service to send (or re-send) the code, then run `otp code`
again to keep waiting:

```json
{ "status": "pending", "next": "no code yet; re-run: otp code --id lease_abc123" }
```

Pass `--since <RFC3339>` (the time you asked the service to send) to ignore any
older code on the same number and wait only for the fresh one.

## release: return the number

```bash
otp release --id lease_abc123
```

Prints `{}`. Release every number once its code is used or you abandon the signup,
so the pool stays available. Releasing an already-released `id` is safe.

## How it authenticates

On a Vesta Cloud box the CLI mints a short-lived server-identity token from vestad
and calls vesta.run, so no setup and no key are needed. A self-hosted box points at
its own Switchboard directly with `SWITCHBOARD_API_URL` plus an `SWITCHBOARD_API_KEY`
(an `sbk_` key handed over by whoever runs that Switchboard); both are required
together. Never print or log the key.
