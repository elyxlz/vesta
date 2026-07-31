# Self-managed WhatsApp account

Use this method whenever the user's phone remains the WhatsApp primary. The user
can link an account already registered on the phone, acquire a number separately,
or—on Vesta Cloud—ask Switchboard to supply a number. Double Tick is not involved.

## Before linking

Confirm that the user intends to give the assistant access to this account. Use
a dedicated WhatsApp account rather than the user's personal account whenever
possible. If they need a separate carrier number, read
[PHONE_NUMBER.md](PHONE_NUMBER.md) or use the optional Switchboard flow below.

Run `whatsapp status`. Stop if it is already linked or an existing link attempt
is active.

## Preferred method: QR

Run:

```bash
whatsapp connect
```

The command starts the daemon and returns one public QR-page URL. Send that URL
to the user. They open it and scan the live code from WhatsApp > Settings >
Linked Devices > Link a Device. The page refreshes the QR automatically.

Wait for the user to confirm the scan, then run `whatsapp status` once. Do not
choose a port, register a tunnel manually, or run another connect while the page
is active.

## Fallback: phone pairing code

Use this only when the user cannot scan a QR and explicitly approves a pairing
attempt:

```bash
whatsapp connect --phone '+12025551234'
```

Confirm the echoed E.164 number exactly. Send the returned code to the user for
WhatsApp > Linked Devices > Link a Device > Link with phone number. Wait while
the code is active; do not generate another.

## Optional: acquire the user's number from Switchboard

`--own-number` is a Vesta Cloud number-acquisition helper inside this
self-managed method, not a Double Tick or fourth setup mode. Use it when
Switchboard should supply the number but the user wants to register and retain
the WhatsApp primary on their phone.

The agent needs its Vesta Cloud tenant identity and Switchboard entitlement. It
does not need or use `DOUBLETICK_API_URL` or `DOUBLETICK_API_KEY`. Do not combine
`--own-number` with `--phone` or `--opener`.

```bash
whatsapp connect --own-number
```

Keep the command running through its three user-visible stages:

1. `register_number`: Switchboard returns a leased number. Give it to the user;
   they register it in WhatsApp on their own phone and request SMS verification.
2. `enter_code`: Switchboard relays the verification code. Give it to the user to
   enter in WhatsApp.
3. QR link: send the returned live page and have the user scan it under Linked
   Devices on the newly registered account.

Switchboard retains the carrier-number/SIM lease and future SMS capability, while
the user's phone owns the WhatsApp primary. Confirm Switchboard's retention and
recovery policy before treating the number as permanent.

## After linking

The user's phone remains responsible for the WhatsApp primary and normal account
maintenance. Normal messaging rules apply; the headless-number reply-first gate
and Double Tick proxy lease do not.

History sync may run for five minutes. Sending is allowed, but daemon stop/restart
is locked. If the phone later removes the companion, ask the user before running
the same connect method again. Future SMS verification for a Switchboard number
must go back through Switchboard, not Double Tick.
