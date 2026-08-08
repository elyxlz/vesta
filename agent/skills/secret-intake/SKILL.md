---
name: secret-intake
description: Take an API key, token, or password from the user without it landing in a chat log. Use whenever you need a credential from them, and instead of ever asking them to paste one into a message.
---

# Secret intake

Every channel persists what the user types, in plaintext, indefinitely. app-chat keeps it in
`~/.app-chat/app-chat.db`, WhatsApp in `~/.whatsapp/messages.db`, and a nightly secret scan is
downstream mitigation: by the time it runs, the value has been at rest on disk for hours or days.
So "paste the key here" writes a live credential into a store that outlives the conversation.

This asks for it over a one-shot web form instead. The user gets a link, opens it on their phone,
types the value once, and it goes straight to `~/.agent-secrets.env`, never through a message.

```bash
secret-intake DOUBLETICK_API_KEY --label "Doubletick API key"
```

It prints a link to send them, then blocks until they submit or the wait runs out. Send them the
link and tell them in chat what it is for; the page itself is deliberately generic.

- `--label "<text>"` is the heading on the page. Defaults to the variable name.
- `--ttl <secs>` is how long the link lives and how long the command waits. Default 900.

## What it guarantees, and what it does not

- The value is never printed, logged, or echoed. The HTTP access log is silenced, because the
  default one prints the request line.
- `~/.agent-secrets.env` is created `0600` and `~/.bashrc` is made to source it, so the value
  survives a restart like any other setting. Setting the same name again replaces it rather than
  stacking a second definition.
- The service is registered private and reached with a freshly minted key in the URL path. On
  exit, whether the value arrived or the wait timed out, the key is revoked and the service
  unregistered, so the link stops working.
- **The link itself is a secret**, and if you send it over chat it lands in the same store the
  credential would have. That is still much better: it is single-purpose, it grants only "submit
  one value", and it dies in minutes, where the credential it carries would have been live for
  months. Keep the TTL short and do not paste the link into anything durable.
- Nothing here protects a value the user has already sent as a message. Scrub that separately, and
  remember that scrubbing narrows the surface and does not undo exposure: **if a live credential
  has sat in plaintext, the fix is rotation, and rotation is the user's call, not yours.**

## Reading it back

`~/.agent-secrets.env` is sourced by `~/.bashrc`, so a new shell has it. A daemon started before
the value arrived is still running with the old environment: restart it (`<skill> daemon restart`)
or it will keep using what it booted with.

## When the credential is a website login

Use the `browser` skill's handover instead (`browser handover start --url "<sign-in URL>"`). The
user signs in on the agent's own browser, the session persists in the profile, and no password is
handled at all. This skill is for a secret that has to end up in the agent's environment, which
handover cannot do.
