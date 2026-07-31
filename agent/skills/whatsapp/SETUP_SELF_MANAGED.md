# Self-managed WhatsApp account

Use this method whenever the user's phone remains the WhatsApp primary. The user
can link an account already registered on the phone, or acquire a number
separately. Double Tick is not involved.

## Before linking

Confirm that the user intends to give the assistant access to this account. Use
a dedicated WhatsApp account rather than the user's personal account whenever
possible. If they need a separate carrier number, read
[PHONE_NUMBER.md](PHONE_NUMBER.md).

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

## After linking

The user's phone remains responsible for the WhatsApp primary and normal account
maintenance. Normal messaging rules apply; the Double Tick account
reply-first gate and proxy lease do not.

History sync may run for five minutes. Sending is allowed, but daemon stop/restart
is locked. If the phone later removes the companion, ask the user before running
the same connect method again.
