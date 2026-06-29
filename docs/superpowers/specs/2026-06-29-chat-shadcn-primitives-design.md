# Chat: rebuild presentational layer on shadcn chat primitives

**Date:** 2026-06-29
**Area:** `apps/web/src/components/Chat/`
**Status:** Design — awaiting review

## Goal

Adopt the newly released shadcn chat components
([changelog](https://ui.shadcn.com/docs/changelog/2026-06-chat-components)) in Vesta's chat,
replacing hand-rolled bubble/tool-call markup with standard primitives, **without changing the
current look** and **without replacing the scroll engine**. Additionally add a shadcn-styled
scroll-to-bottom button wired to the existing virtualizer.

## Decisions (settled)

- **Scope:** Visual primitives only. The `ChatMessageArea` TanStack virtualizer
  (`@tanstack/react-virtual`), `ChatComposer`, `BottomBanner`, and `Chat/index.tsx`
  orchestration stay as-is.
- **Look:** Preserve the current appearance (squircle bubbles, inline tucked timestamp,
  mobile-fullscreen `bg-card` + ring/shadow, mask fades). Primitives are restyled back to the
  bespoke look via `className`.
- **Attachments:** Skipped (chat is text-only today — YAGNI).
- **Scroll engine:** NOT swapped. We do not adopt `MessageScroller` or its `@shadcn/react`
  dependency.
- **Scroll-to-bottom button:** Add it, but driven by the existing virtualizer rather than the
  shadcn scroller context (see below).

## Components to install

From the `@shadcn` registry: `bubble`, `message`, `marker`.

- None pull new runtime deps — they import only `cn`, radix `Slot`, and `cva`, all already in
  the project.
- **Not installed:** `message-scroller` (needs the `@shadcn/react` npm package + uses
  `content-visibility` instead of true windowing + has a Next.js-specific `IconPlaceholder`
  import) and `attachment`.
- After `add`, verify the CLI rewrote the registry's `@/registry/radix-luma/lib/utils` import
  to the project's `@/lib/utils` alias.

## Changes

### 1. `ChatBubble` → `Message` + `Bubble` + `BubbleContent`

Current: a hand-rolled `flex justify-{end,start}` row wrapping a styled `div` with markdown +
an inline timestamp.

New composition:

- `Message` with `align="end"` (user) / `align="start"` (agent) replaces the manual
  `justify-*` flex row.
- `Bubble` + `BubbleContent` for the surface. Variant mapping aligns with the current palette
  exactly:
  - user → `variant="default"` (`bg-primary` / `text-primary-foreground`)
  - agent → `variant="secondary"` (`bg-secondary` / `text-secondary-foreground`)
- Preserve look via `className` on `BubbleContent`:
  - override shadcn's default `rounded-3xl` back to the squircle
    (`rounded-squircle-sm [corner-shape:squircle]`) + tail (`rounded-br-sm` / `rounded-bl-sm`).
  - keep the timestamp **inline, tucked at the end inside the bubble** (current behavior), not
    in a `MessageFooter`.
  - keep the mobile-fullscreen treatment: agent bubble `bg-card` + `shadow-md` +
    `ring-1 ring-foreground/5 dark:ring-foreground/10`.
  - keep `max-w-[85%]`, `text-sm leading-relaxed`, `min-w-0 break-words` on the markdown.
- `ChatBubble` keeps its current responsibilities: returns `null` for history/status, renders
  `ToolCallLabel` for `tool_start`, renders the bubble for `user`/`chat`. `memo` retained.

> Note: "preserve look" requires `className` color/radius overrides on `BubbleContent`, which
> runs against the shadcn guideline "className for layout, not styling." This is an explicit,
> user-chosen tradeoff (bespoke look wins) and is confined to `ChatBubble`/`ToolCallLabel`.

### 2. `ToolCallLabel` → `Marker` + `Collapsible`

Current: an expandable pill (`rounded-full` collapsed → `rounded-2xl` expanded) with wrench
icon + label + chevron + a `<pre>` of the input.

New composition:

- `Marker variant="default"` as the activity row (Marker's documented purpose is "tool
  activity updates").
- `Collapsible` / `CollapsibleTrigger` / `CollapsibleContent` (already installed) for the
  expand/collapse of the raw input, replacing the local `useState` toggle.
- Preserve the pill affordance and current styling via `className`; keep the wrench icon,
  `TOOL_LABELS` map, chevron rotation, and the monospace input block.
- `memo` retained.

### 3. Scroll-to-bottom button (new)

shadcn's `MessageScrollerButton` is bound to the `MessageScroller` engine and cannot be used
standalone. We replicate its **appearance and behavior** against the existing virtualizer.

- In `ChatMessageArea`, track an `atBottom` boolean in state:
  - update inside the existing `onScroll` handler (`virtualizer.isAtEnd(AT_BOTTOM_THRESHOLD_PX)`),
  - and recompute when the row `count` changes (new message while scrolled up should reveal the
    button).
- Render a floating button inside the message area's `relative` `CardContent`, positioned
  bottom-center, above the bottom mask fade:
  - shadcn treatment: `Button variant="secondary" size="icon-sm"`, lucide `ArrowDown`,
    `sr-only` label "Scroll to end".
  - visible when `!atBottom`, hidden when pinned — replicate the `data-active` transition from
    the `MessageScrollerButton` source (opacity + scale + translate-y, with the asymmetric
    ease-in/ease-out cubic-beziers).
- Click → `virtualizer.scrollToEnd({ behavior: "smooth" })`.
- Does **not** draw a divider line (respects the "no dividers inside cards" rule).

### Deliberately unchanged

- Day-stamp dividers, "beginning of conversation", the "loading…" pill, and the typing
  indicator stay as their current centered-text markup. Marker's `separator`/`border` variants
  draw lines and are forbidden by the CLAUDE.md hard rule "No dividers inside cards"; Marker's
  `default` variant adds no value over the current centered spans, so these are left alone.
- `ChatMessageArea` virtualization config (anchoring, `directDomUpdates`, overscan, mask
  gradients, load-older paging, skeleton) — untouched except for the `atBottom` state + button.
- `ChatComposer`, `BottomBanner`, `Chat/index.tsx`, `use-chat-keyboard-focus.ts`,
  `ChatHeaderActions`, `virtual.ts`.

## Verification

- `./check.sh web` green (eslint + prettier --check + tsc + vitest).
- `virtual.test.ts` unaffected (no changes to `virtual.ts`).
- Manual spot-check: user bubble (right, primary), agent bubble (left, secondary), mobile
  fullscreen treatment, an expanded tool call, and the scroll-to-bottom button appearing when
  scrolled up + scrolling smoothly to the latest message on click.

## Out of scope

- `MessageScroller` / `@shadcn/react` adoption.
- `Attachment` wiring.
- Any change to chat data flow, `ChatProvider`, or event types.
