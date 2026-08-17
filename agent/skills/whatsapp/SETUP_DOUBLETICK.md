# Double Tick WhatsApp account

A standalone Double Tick service provides a dedicated, headless WhatsApp account
end to end. Requests go straight to Double Tick and never traverse Vesta Cloud.
Use this when a non-cloud agent points at such a service.

## Prerequisites

The user has the Double Tick API base URL and one account-scoped key. If both are
already set in the environment (`DOUBLETICK_API_URL` and `DOUBLETICK_API_KEY`), use
them. Otherwise ask the user for both, then connect.

Run `whatsapp status` first; stop if linked or connecting.

## Connect

Compose a short, natural opener from the user's perspective. Set the two values for
this one command; the daemon saves them in owner-only state for later boots, so
they need no export:

```bash
DOUBLETICK_API_URL='https://doubletick.example' \
DOUBLETICK_API_KEY='wak_account-scoped-key' \
  whatsapp connect --source doubletick --opener 'Hi, it is me, nice to meet you here'
```

When both values are already exported, the bare command works:

```bash
whatsapp connect --source doubletick --opener 'Hi, it is me, nice to meet you here'
```

Pass an opener that has an apostrophe or newline through stdin with `--opener -`,
the same heredoc form `send --message -` uses:

```bash
whatsapp connect --source doubletick --opener - <<'OPENER'
hey it's me, let's talk here from now on
OPENER
```

The CLI authenticates to Double Tick with the `wak_` key, provisions or recovers
the account, and pairs the companion over the account's
[residential proxy lease](HEADLESS.md#residential-proxy-lease). It saves the
credentials in mode-`0600` WhatsApp state, so do not restart the daemon to make new
credentials visible.

Link this alongside another account, or when the default instance is held or in
use, by putting it on its own named instance: start that instance's daemon first,
keep `--instance` on every later command, and add its `whatsapp daemon start` line
to your restart daemons. See [Named instances](SETUP.md#named-instances).

```bash
whatsapp daemon start --instance work
whatsapp connect --source doubletick --instance work --opener 'Hi, it is me'
```

Follow the returned `next`. Reply-first behavior is in [SKILL.md](SKILL.md);
recovery outcomes are in [SETUP.md](SETUP.md#status-and-recovery). Use the Double
Tick service's own status and logs for the account.
