---
name: design-engineering
description: Use when building, changing, or reviewing UI animation, motion, or interaction design: choosing easing, duration, springs, or transform-origin; deciding whether something should animate at all; gesture-driven UI (drag, swipe, sheets, momentum, interruptibility); hover/press states and UI polish details; when the user describes a motion effect and wants its exact name; or when explicitly asked to review animation code for craft.
---

# Design Engineering

Emil Kowalski's design-engineering skills (animations.dev), vendored from [emilkowalski/skills](https://github.com/emilkowalski/skills) as one skill with sub-references. Load only the file the task needs:

| Task | Load |
| --- | --- |
| Writing or changing animations and UI polish: easing, duration, transform-origin, springs, hover/press states, whether to animate at all | [design.md](design.md) |
| Gesture-driven or fluid UI: drag, swipe, sheets, momentum, interruptible transitions, translucent materials, typography | [apple.md](apple.md) |
| The user describes a motion effect and wants the right term to ask for | [vocabulary.md](vocabulary.md) |
| The user explicitly asks to review animation or motion code | [review.md](review.md), pulling exact values from [standards.md](standards.md) |

Rules:

- Run the review workflow in review.md only when the user explicitly asks for an animation review (it was upstream's `disable-model-invocation: true` skill); never self-trigger it.
- design.md and apple.md overlap on springs and interruptibility: design.md is the default, apple.md when the interaction is gesture-driven or aiming for the Apple fluid feel.
- When a finding or implementation needs a precise value (a cubic-bezier curve, a duration budget, a spring config), take it from standards.md rather than approximating.
