---
name: frontend-design
description: Design judgment for building dashboard widgets that feel intentional and crafted rather than templated, within Vesta's fixed design system. Structure, restraint, motion, and UI copy.
license: MIT (anthropics/claude-code), adapted
---

<!-- Adapted from anthropics/claude-code plugins/frontend-design/skills/frontend-design/SKILL.md (MIT). Trimmed to what applies to dense dashboard widgets inside Vesta's fixed design system. The brand identity, hero, distinctive-typography, and invent-a-palette guidance is dropped on purpose: the dashboard's fonts, base theme, and color tokens are synced (index.css + shadcn) and must not change. Kept: intentionality, structure, restraint, self-critique, motion, and writing/copy. -->

# Frontend Design (dashboard context)

You design dense dashboard widgets inside a fixed system: the fonts, base theme, and color tokens are synced from the main app (`index.css`, shadcn), and the density rules are set. You do not choose fonts or invent palettes. Your craft is composition, hierarchy, structure, motion, restraint, and copy. Make deliberate choices that fit this specific data, not the templated defaults you would reach for on any dashboard.

## Structure is information

Structural devices (numbering, eyebrows, dividers, labels) should encode something true about the content, not decorate it. Numbered markers (01 / 02 / 03) are only appropriate when the content actually is a sequence: a real process, or an ordered timeline where order carries information the reader needs. Question whether a device makes sense before using it.

## Match complexity to the data

A dense, minimal surface needs precision in spacing, type scale, and detail rather than more elements. Elegance is executing the chosen layout well. Combine related information into single rows, and let each widget say one thing clearly.

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
- Treat failure and empty states as direction, not mood. Say what went wrong and how to fix it, in the interface's voice. An empty widget is an invitation to act, not blank space.
- Keep the register plain: sentence case, no filler, tone matched to the user. Each element does one job. A label labels, a value shows, and nothing does double duty.
