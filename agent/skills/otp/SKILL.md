---
name: otp
description: Use when you need a one-time SMS verification code on a temporary phone number to sign up for or verify a service (a phone-number signup, an SMS 2FA step, a "we texted you a code" screen). For WhatsApp, use the `whatsapp` skill instead.
---

# otp (CLI: `otp`)

Get a one-time SMS code on a temporary number, use it to clear a service's phone
verification, then give the number back. Install the `otp` command once from
[SETUP.md](SETUP.md). Three verbs run in order:

1. `otp new --source <s> --service <name>` reserves a number and returns its `id`.
2. Enter that number as the phone number on the service you are verifying.
3. `otp code --source <s> --id <id>` waits for the code the service texts, and prints it.
4. `otp release --source <s> --id <id>` returns the number once you are done.

Every command prints JSON: success on stdout, and any failure on stderr with a
non-zero exit, so it survives piping stdout through grep/head/jq. `--source` is
required on every verb: you state where the number comes from (see below), the
CLI never guesses, and `code`/`release` take the same source the number was
reserved with. The number is temporary, so
release it as soon as the code is used. Do not reuse an `id` for a second service.

## Choosing `--source`

Two independent services can supply numbers; you decide which to use:

- `--source vesta-cloud`: Vesta Cloud. Works on any box with a Vesta Cloud account
  (run `vesta-cloud whoami` when unsure; `account: true` means it works), with
  no setup and no key. With no account the reserve fails with a clear error;
  the box can be connected to a Vesta Cloud account, and the `vesta-cloud`
  skill's SKILL.md explains how.
- `--source switchboard`: a Switchboard the owner runs. Needs
  `SWITCHBOARD_API_URL` plus `SWITCHBOARD_API_KEY` (an `sbk_` key handed over
  by whoever runs that Switchboard); both are required together. Never print or
  log the key.

## new: reserve a number

```bash
otp new --source vesta-cloud --service github
otp new --source switchboard --service coinbase --country US
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

Four failures (each printed as JSON on stderr, exit non-zero) are not errors to
retry blindly, so read the `error` key from stderr before deciding:

- `{ "error": "otp_quota_exceeded", "next": "..." }`: the account's OTP allowance
  is spent. Wait for it to reset. Do not retry in a loop.
- `{ "error": "out_of_stock", "next": "..." }`: no number is free right now. Retry
  shortly, or pass a different `--country`.
- An error containing `membership_inactive`: this box's Vesta Cloud account has no
  active paid membership, so Vesta Cloud OTP numbers are closed. Tell the owner;
  do not retry.
- An error containing `no server identity available` (from the token mint): this
  box has no Vesta Cloud account and no `sbk_` key. Check `vesta-cloud whoami`;
  the box can be connected to Vesta Cloud, and the `vesta-cloud` skill explains
  how.

## code: wait for the SMS

```bash
otp code --source vesta-cloud --id lease_abc123
otp code --source vesta-cloud --id lease_abc123 --since 2026-07-31T18:00:00Z
```

`otp code` polls until the code lands or a bounded timeout, then prints:

```json
{ "code": "482913" }
```

If the SMS has not arrived within the timeout, it prints a pending status instead
of failing. Trigger the service to send (or re-send) the code, then run `otp code`
again to keep waiting:

```json
{ "status": "pending", "next": "no code yet; re-run: otp code --source vesta-cloud --id lease_abc123" }
```

Pass `--since <RFC3339>` (the time you asked the service to send) to ignore any
older code on the same number and wait only for the fresh one.

## release: return the number

```bash
otp release --source vesta-cloud --id lease_abc123
```

Prints `{}`. Release every number once its code is used or you abandon the signup,
so the pool stays available. Releasing an already-released `id` is safe.
