# Self-managed account

The user supplies a dedicated WhatsApp account for the agent, registered on a SIM
they procure themselves (their own phone number). That account runs either as a
second WhatsApp account on the user's existing phone or on a separate/spare phone
they control, and the agent links to it as a companion. It is a dedicated
assistant account, never the user's personal WhatsApp. Double Tick, the proxy
lease, and the reply-first gate do not apply; normal messaging rules do.

## Before linking

Confirm the user intends to give the assistant access to this dedicated account.
The user must supply their own SIM / phone number; if they need to acquire one,
read [GET_A_NUMBER.md](GET_A_NUMBER.md).

Run `whatsapp status`; stop if already linked or an attempt is active.

## Preferred: QR

```bash
whatsapp connect --source self-managed
```

Returns one public QR-page URL. Send it to the user; they scan the live code from
WhatsApp > Settings > Linked Devices > Link a Device (the page refreshes the QR
itself). Wait for their confirmation, then run `whatsapp status` once. Do not
choose a port, register a tunnel by hand, or start another connect while the page
is active.

## Fallback: phone pairing code

Only when the user cannot scan a QR and explicitly approves a pairing attempt:

```bash
whatsapp connect --source self-managed --phone '+12025551234'
```

Confirm the echoed E.164 number exactly. Send the returned code for
WhatsApp > Linked Devices > Link a Device > Link with phone number. Wait while it
is active; do not generate another.

## After linking

History sync may run for five minutes: sending works, but daemon stop/restart is
locked. If the phone later removes the companion, ask the user before running the
same connect method again.
