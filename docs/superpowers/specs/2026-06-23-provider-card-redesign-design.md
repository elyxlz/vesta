# ProviderCard redesign

**Date:** 2026-06-23
**Scope:** `apps/web/src/components/AgentSettings/ProviderCard/index.tsx` (one file)

## Problem

The current provider card in agent settings reads as plain and list-like. Four
concrete weaknesses, confirmed with the user:

1. **No provider branding.** The header uses a generic `Cpu` icon; nothing
   signals whether Claude or OpenRouter is active.
2. **Weak information hierarchy.** Provider label, model, and context window are
   three near-identical muted lines; the model — the thing you most want to read
   — doesn't stand out.
3. **Button clutter.** Four equal full-width buttons (change model, change
   context window, switch provider, sign out) make routine edits look as heavy
   as rare and destructive ones.
4. **Plain visual polish.** Flat stack, no intentional grouping.

## Non-goals

- No API, hook, or data-shape changes. `useProvider`, `useUsage`,
  `useClaudeModels`, and the `setModel` / `setContextWindow` / `signOutProvider`
  calls are untouched.
- The model dialog, context dialog, and sign-out `AlertDialog` keep their
  current behavior and copy. Only the card's presentation changes.
- No changes to `ProviderPicker` or the switch-provider flow (`handleOpenAuth`).

## Design (Approach B: branded header + compact action bar)

### 1. Identity header

Replaces the `Cpu` + the three-line info block.

- A squircle logo tile with a brand-tinted background holding the provider's
  brand mark, resolved via `providerMeta(provider.kind).Logo` —
  `ClaudeLogo` (tint `#D97757`) or `OpenRouterLogo` (foreground). Branding stays
  owned by `providers.ts`/`logos`; no SVGs hardcoded in the card.
- A text column with `min-w-0`:
  - Provider label as a small muted eyebrow: `Claude account` / `OpenRouter`.
  - **Model name as the headline** (`text-sm font-medium`), with `truncate` and
    a `title` attribute so long OpenRouter slugs (e.g.
    `anthropic/claude-3.5-sonnet`) don't overflow the card.
  - Context window as a small `Badge variant="secondary"`: `1M context` /
    `200k context` / `default`, reusing the existing `formatTokens` + default
    logic (`max_context_tokens` present → `formatTokens`; else OpenRouter →
    `default`, Claude → `1M (default)`).

### 2. Usage block

Logic unchanged. Keeps `UsageBar`, the refresh spinner, skeleton loading state,
and the error / empty / loaded states (meters + credits). Sits in its own
`border-t pt-3` section.

### 3. Action bar

Replaces the four stacked buttons with one horizontal row (`border-t pt-3`):

- Two compact `outline` `size="sm"` buttons sharing the row, `flex-1` so they
  split the width and wrap cleanly on narrow screens:
  - **change model** → opens the existing model `Dialog`.
  - **context** (shortened label) → opens the existing context `Dialog`.
- A `⋯` overflow `DropdownMenu` (ghost icon-button trigger) on the right holding
  the infrequent / destructive actions:
  - **switch provider** (`ArrowLeftRight`) → `handleOpenAuth`.
  - **sign out** (`LogOut`, `text-destructive` menu item) → opens the existing
    sign-out `AlertDialog`.

## Edge cases

- **Long OpenRouter model slugs:** header text column is `min-w-0` and the model
  line `truncate`s with a `title` tooltip.
- **Context window display:** unchanged from current logic.
- **Mobile / narrow card:** the two action buttons are `flex-1`; the row wraps
  gracefully with the `⋯` menu.
- **`provider.kind === "none"` / null provider:** still returns `null` early, as
  today.

## Verification

- `./check.sh web` — tsc, eslint, prettier must pass.
- Visual check in the running app for the actual look (per the user's
  "verify UI visually" rule). If the app can't be run in this session, the change
  is flagged as visually-unverified rather than claimed done.

## Conventions to honor

- Lowercase UI copy (matches the rest of the app: `provider`, `change model`).
- Tailwind utility classes only; no new styles file.
- Reuse existing primitives: `Badge`, `DropdownMenu`, `Button`, `Card`.
- "Agent" terminology; no `any`; named exports.
