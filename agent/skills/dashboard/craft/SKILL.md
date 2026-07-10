---
name: dashboard-craft
description: Design judgment and UI copy for building Vesta dashboard widgets that feel considered rather than templated, within the fixed design system.
license: MIT (anthropics/claude-code), adapted and extended
---

<!-- Design-judgment sections (structure, match-complexity, motion, restraint, self-critique, CSS gotcha, writing/copy) are adapted from anthropics/claude-code plugins/frontend-design (MIT), trimmed to the dashboard context. The brand-identity, hero, distinctive-typography, and invent-a-palette guidance is dropped on purpose: the dashboard's fonts, base theme, and color tokens are synced (index.css + shadcn) and must not change. The dashboard-specific sections (hierarchy, color, charts, family, states) are ours. -->

# Dashboard Craft

The craft of building dashboard widgets that feel considered. You work inside a fixed system: the fonts, base theme, and color tokens are synced from the main app (`index.css`, shadcn), and the density rules are set. You do not choose fonts or invent palettes. Your craft is hierarchy, composition, structure, color as signal, motion, restraint, and copy. Make deliberate choices that fit this specific data, not the templated defaults you would reach for on any dashboard.

## One thing per widget

Each card leads with a single primary value, its reason to exist, set large; everything else is secondary and muted. If a widget has two equally loud numbers, split it into two or demote one. The eye should land in one place, then travel to the supporting detail.

## Color carries meaning, not decoration

Structure follows the design system. Buttons, cards, inputs, borders, and surfaces use the semantic Tailwind tokens that are automatically synced from the main app into `index.css` (`primary`, `secondary`, `muted`, `accent`, `destructive`, `warning`, `border`, and the `card`/`background`/`foreground` families), so the dashboard matches the wider app and stays in step with its theme. You never edit `index.css`; those tokens are always current, build against them.

Raw scales (`text-green-500`, `bg-amber-100`) are fine where you need a color a token does not cover: a value that is up or down, a chart series, a status dot, a category. Reserve them for signal, not decoration, and use them the same way across every widget so the user learns them once. A widget washed in one accent has no signal left to give.

## Structure is information

Structural devices (numbering, eyebrows, dividers, labels) should encode something true about the content, not decorate it. Numbered markers (01 / 02 / 03) belong only when the content actually is a sequence: a real process or an ordered timeline where order carries information the reader needs. Question whether a device makes sense before using it.

## Charts stay quiet

In a dense card a chart is a glance, not a report. Drop gridlines, legends, and axis clutter; label only the value that matters. A sparkline or a few bars beside the number usually beats a full chart. Match the chart's color to its meaning, not to a default palette.

## Match complexity to the data

A dense, minimal surface needs precision in spacing, type scale, and detail rather than more elements. Elegance is executing the chosen layout well. Combine related information into single rows, and let each widget say one thing clearly.

## Widgets are a family

A new widget should look like it belongs next to the others on its page: the same card shape, label style, icon treatment, and spacing. Read the neighboring widgets and match them before inventing anything. Consistency is how the dashboard reads as one product rather than a pile of parts.

## States are part of the design

Design the loading, empty, and error states, not just the happy path. Loading is a skeleton shaped like the widget, not a spinner dropped in a tiny card. Empty is a short line of direction, not blank space. Error says what went wrong and how to fix it.

## Motion, sparingly

Use animation deliberately and rarely. A subtle state transition or a single load reveal can help; scattered micro-interactions read as AI-generated, and less is usually more. Respect reduced motion.

## Restraint and self-critique

Spend your boldness in one place and keep everything around it quiet and disciplined; cut any decoration that does not serve the data. Build to a quality floor without announcing it: responsive down to mobile, visible keyboard focus, reduced motion respected. Critique your own work as you build. Consider Chanel's advice: before you finish, look again and remove one thing.

## CSS gotcha

Be careful with selector specificity: it is easy to generate classes that cancel each other out (a type-based selector like `.section` fighting an element-based one), which shows up most in the paddings and margins between sections.

## Writing and copy

Words in a widget exist to make it easier to understand and use. They are design material, not decoration. Bring the same intention to copy that you bring to spacing.

- Write from the user's side of the screen. Name things by what people control and recognize, never by how the system is built (a person manages notifications, not webhook config).
- Use active voice. A control says exactly what happens when it is used ("Save changes", not "Submit"), and keeps the same name through the flow (a "Publish" button produces a "Published" toast).
- Treat failure and empty states as direction, not mood. Say what went wrong and how to fix it, in the interface's voice. An empty widget is an invitation to act.
- Keep the register plain: sentence case, no filler, tone matched to the user. Each element does one job. A label labels, a value shows, and nothing does double duty.
