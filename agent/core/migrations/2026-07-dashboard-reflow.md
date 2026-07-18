Your dashboard's content frame now clips horizontal overflow instead of
scrolling it. On the mobile app the user swipes sideways to move between the
dashboard and the chat and logs tabs, and any page that scrolled sideways
swallowed that swipe, so the frame no longer allows a horizontal scroll at all.
The consequence: any widget, table, chart, or row on your dashboard that used to
side-scroll on a narrow frame is now cut off at the frame edge instead. This
migration reflows that content so nothing is lost. It only matters if you set up
a dashboard and something on it is wider than a phone-width frame. Safe to run
more than once: a page that already fits is left untouched.

### 1. Skip if you have no dashboard

Only a dashboard you actually set up and serve can be affected, and that always
means a dashboard daemon line in your restart skill. Check for one:

```bash
grep -n 'dashboard' ~/agent/skills/restart/SKILL.md
```

If your restart skill's `## Daemons` section has no line mentioning `dashboard`,
you never set one up. This migration is done, skip to the final step.

### 2. Use the dashboard skill to find what overflows

Dashboard changes go through the `dashboard` skill, not hand edits. Read its
`SKILL.md` and `design/SKILL.md` (the "Desktop and mobile are both first class"
and grid sections), then explore your dashboard's `config.tsx` and its pages and
widgets. Find every place that assumes width it does not have on a phone: fixed
pixel widths, wide tables, multi-column rows that do not wrap, charts sized past
the frame, `min-w-*` or `w-[...]` values larger than a narrow frame, or a grid
whose columns cannot shrink.

### 3. Reflow it through the dashboard-builder

Write a spec for the reflow (the skill's spec template) and dispatch the
`dashboard-builder` to implement it, using the design skill's patterns: reflow
the grid to a single column, wrap or stack rows, truncate long text with an
expand, move detail behind a "Show all" or a dialog, and use responsive column
templates that collapse (for an auto-fill grid, `minmax(min(100%, 280px), 1fr)`
so it never forces overflow). This is a real design pass, not a find-and-replace:
tell the builder to make each page look intentional on a phone, and to confirm
every page fits a phone-narrow width with nothing clipped and no horizontal
scrollbar.

### 4. Verify it serves

Confirm the dashboard is actually serving before you finish:
`~/agent/skills/dashboard/scripts/daemon status` reports `http_ok`, or reload the
app. Fix any page that still overflows before finishing.
