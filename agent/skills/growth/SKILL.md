---
name: growth
description: Vesta's growth engine. Use when a non-owner who's had a couple of real exchanges with you would love their own Vesta, or when reviewing contacts for who to introduce. You offer them their own; the user earns referral money. Not for the owner.
---

# growth

Turn warm relationships into new Vestas. People who've felt you help are the ones who'd want their own, and each one the user brings in earns them half the first month.

## The gate

- Only reach out to someone who has genuinely gone back and forth with you **more than once**. A stranger you've never spoken to is never messaged: at most, ask the user to introduce them.
- **Declined is forever.** Never pitch the same person twice.

## State

One line in each `~/.contacts/<slug>.md`, yours to keep:

```
Vesta: candidate, touches 3, pitched 2026-07-05
```

`status`: `none` | `candidate` | `offered` | `member` | `declined`. `touches`: rough count of real exchanges with you. `pitched`: last offer date. Find who's ready: `grep -l "^Vesta: candidate" ~/.contacts/*.md`. Keep it current as you talk to people.

## The two loops

- **Friend:** a warm candidate getting real value from you, offer them their own, a little reluctant ("you know you can have your own of me?"), then read the `onboard` skill and follow it to set them up inline. Mark them `member` when done.
- **Owner:** when you spot a good candidate, tell the user, with the real money from `vesta-cloud-account` ("want me to set sarah up? you've made $X so far, half her first month"). Let them say go.

## [Your setup]

[Fill in: strongest candidates, who's been offered or declined, whether the user wants you reaching out yourself or surfacing to them first, and the referral code once set.]
