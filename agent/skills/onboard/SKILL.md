---
name: onboard
description: Use when someone who doesn't yet have their own vesta asks what this is or how to get one. Walks them through signup end to end — explains the product, collects email + subdomain + plan and how they want it set up (name, personality, starting skills), sends a Stripe checkout link, then hands off to the web app and the desktop/mobile installers. Never asks for card details (Stripe handles payment). Do NOT use to onboard the owner (they already have one).
---

# onboard - CLI: `onboard`

Introduce a stranger to Vesta and walk them to owning their own. This is the
product's growth loop: anyone messaging your vesta on any channel can ask "what
is this / how do I get one", and you guide them through signup. If your vesta is
a **paid (hosted) account**, a completed referral earns you **50% of the referred
user's first month**; self-hosted vestas can still onboard people, they just
aren't paid for it.

You never see the stranger's card or password — only the email they type and the
public Stripe Checkout URL. Everything sensitive happens on their own device.

## Trigger

Invoke this skill when someone **who does not already have a vesta**:
- asks what Vesta is, how it works, or how to get their own;
- says they want one / wants to sign up / wants the app.

## Skip

- The **owner** of this vesta (they already have one — don't pitch them).
- Anyone mid-conversation about something unrelated — don't derail into a sales
  pitch unprompted. The owner can disable pitching entirely (see *Preference*).
- Requests to pay for something else — that's `stripe-pay`, not this.

## How to run the conversation

Keep it human and short — a couple of messages, not a monologue. Link the
marketing page rather than reciting everything (`onboard links`).

1. **Explain in a sentence or two.** A personal AI on its own always-on server
   that remembers them and runs their skills; they bring their own model provider
   (a Claude account, ChatGPT/Codex, or an OpenRouter key — connected per agent
   *after* setup); you operate the box so they don't. Pricing is **$12 Starter /
   $24 Pro / $48 Power per month** (annual = 2 months free). Quote real numbers;
   don't invent discounts.
2. **Collect what signup needs**, conversationally:
   - **email** (their receipts + sign-in land here),
   - **subdomain** — `they.vesta.run`. Validate it live with `onboard check`
     before promising it; if taken/invalid, ask for another.
   - **plan** — `starter` | `pro` | `power`.
   - **How they want it set up** (all optional, sensible defaults if they don't
     care): a **name**, a **personality** preset, and any **starting skills**
     (calendar, email, spotify, …). See `onboard presets`.
3. **Mint the checkout link** with `onboard start` and send it. Then **stop** —
   do not ask for card numbers; Stripe Checkout collects payment on their device.
4. **Wait for them to pay**, then poll `onboard status`. When it reports the
   subdomain is taken (signup went through), send the handoff: the dashboard at
   `vesta.run/dashboard` (sign in with the email they gave, 6-digit code), the
   desktop/mobile install links (`onboard links`), and the one remaining step —
   **connect a model provider** (Claude / ChatGPT-Codex / OpenRouter) to their
   agent inside the app.

Be a friendly introducer throughout. If they're not interested, drop it.

## Usage

```bash
onboard check <subdomain>                          # is they.vesta.run free?
onboard start --email <e> --subdomain <s> --plan <starter|pro|power> \
              [--name <n>] [--personality <preset>] [--skills a,b,c]
                                                   # -> { url } Stripe checkout link
onboard status --subdomain <s>                     # did signup go through yet?
onboard presets                                    # personality presets + installable skills
onboard links                                      # marketing + desktop/mobile install URLs
```

All commands print **JSON** to stdout. `start` returns `{ "url": "https://checkout.stripe.com/..." }`
— send that URL verbatim and stop.

### Examples

```bash
onboard check ada
# { "subdomain": "ada", "available": true }

onboard start --email ada@example.com --subdomain ada --plan pro \
              --name Ada --personality dry --skills email-client,tasks
# { "url": "https://checkout.stripe.com/c/pay/cs_test_..." }

onboard status --subdomain ada
# { "subdomain": "ada", "status": "pending" }   (still free → not signed up yet)
# { "subdomain": "ada", "status": "signed_up" } (taken → they completed checkout)
```

## Referral attribution (automatic)

If this vesta is hosted, its **non-secret `referral_code`** is read from the
`VESTA_REFERRAL_CODE` environment variable and sent with `onboard start` so a
completed signup credits this account. If the variable is unset (self-hosted, or
not provisioned with one), signup still works — there's just no referral and no
reward. You never need to handle the code yourself; the CLI does it. Override for
testing with `--referral <code>`.

## Caveats

- **Never collect or relay card details.** Stripe Checkout handles payment on the
  stranger's own device. Your job ends at sending the link.
- **Validate the subdomain before promising it** (`onboard check`) — names are
  lowercase letters/digits/hyphens; some are reserved.
- **One link at a time.** Don't fan out parallel `onboard start` calls.
- **Defaults are fine.** If they don't want to pick a name/personality/skills,
  proceed without them — the new vesta boots with sensible defaults.
- The control-plane base URL defaults to `https://vesta.run/api`; override with
  the `VESTA_CONTROL_URL` environment variable.

## Preference

`allow_onboarding` (default **on**) governs only whether this vesta should pitch
Vesta to people who ask. It is **not** an access control — it just lets an owner
who doesn't want their assistant doing sales turn the pitch off. When off, decline
politely and point to `vesta.run`.

## Setup

The CLI is bundled; install it once (the agent does this on first use):

```bash
uv tool install ~/agent/skills/onboard/cli
```
