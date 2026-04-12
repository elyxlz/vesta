---
name: dashboard
description: Use when you need to build, modify, or customize anything on the user's dashboard — widgets, layouts, pages, views, or any custom UI.
serve: PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H 'Content-Type: application/json' -d '{"name":"dashboard"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])") && screen -dmS dashboard sh -c "cd ~/vesta/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
---

# Dashboard

A React app embedded in the main Vesta app that serves as the user's **life HQ** — a personal command center for health, finances, productivity, habits, goals, and anything else they want to track and manage. Uses a sidebar layout with page-based navigation. The agent configures pages, sidebar items, and content by editing `config.tsx` and creating page components.

## Before building (REQUIRED)

**Check if shared files need syncing:** Compare `$VESTA_VERSION` against `cat ~/vesta/skills/dashboard/app/.last-sync`. If they differ (or `.last-sync` doesn't exist), run `~/vesta/skills/dashboard/sync-app.sh` and rebuild. This ensures the dashboard uses the same UI components and styles as the main app.

You MUST ask the user clarifying questions before writing any code. Go through these:

1. **Goal** — if the request is vague, clarify what they actually want to see or do
2. **Interaction** — display-only, or do they want to tap/click/toggle/input things?
3. **Data** — should it show fixed sample data, or pull in live data from a skill or API? Does the info need to stay in sync and look the same across different Vesta apps (like mobile)?

Only start building once the user has answered. Don't assume — ask.

## Project structure

```
~/vesta/skills/dashboard/app/src/
├── App.tsx              ← layout shell (sidebar + content area)
├── config.tsx           ← EDIT THIS: define pages, sidebar nav, branding
├── main.tsx             ← do NOT modify
├── index.css            ← do NOT modify (synced from main app)
├── pages/               ← page components (one per sidebar nav item)
├── examples/            ← reference components (read for inspiration)
│   ├── section-cards.tsx       ← metric cards with trend badges
│   ├── chart-area-interactive.tsx ← interactive area chart
│   └── layout-example.tsx      ← grid layout with widget span patterns
├── components/
│   ├── ui/              ← shadcn components (synced, do NOT modify)
│   ├── app-sidebar.tsx  ← sidebar component (reads from config)
│   ├── site-header.tsx  ← header with page title
│   ├── nav-main.tsx     ← main nav items
├── widgets/             ← reusable widget components
├── lib/
│   ├── parent-bridge.ts ← auth + API helpers
│   └── utils.ts         ← synced utility (do NOT modify)
└── hooks/               ← synced hooks (do NOT modify)
```

**You can freely edit:** `config.tsx`, `App.tsx`, anything in `pages/`, `components/`, `widgets/`, and any new files you create

**Do NOT modify:** `main.tsx`, `index.css`, `lib/utils.ts`, `hooks/`, `components/ui/`

## How it works

The dashboard uses a **sidebar + page** layout. The agent controls what appears by editing `config.tsx`:

```tsx
// config.tsx
import { OverviewPage } from "./pages/overview"
import { AnalyticsPage } from "./pages/analytics"
import { LayoutDashboardIcon, ChartBarIcon } from "lucide-react"

export const config: DashboardConfig = {
  title: "Vesta",                                    // sidebar header
  titleIcon: <CommandIcon className="size-5!" />,    // sidebar header icon
  pages: [
    { id: "overview", title: "Overview", icon: <LayoutDashboardIcon />, component: OverviewPage },
    { id: "analytics", title: "Analytics", icon: <ChartBarIcon />, component: AnalyticsPage },
  ],
}
```

Each `pages` entry creates a sidebar nav item. Clicking it renders that page's `component` in the content area.

### Organizing widgets into pages

When the user asks to add a widget without specifying which page, **choose a fitting page name yourself**. Group related widgets under a meaningful category with an appropriate lucide icon. For example, a water intake tracker would go under a "Health" page with `<HeartIcon />`, a stock ticker under "Finance" with `<DollarSignIcon />`, a to-do list under "Productivity" with `<CheckSquareIcon />`. If a suitable page already exists, add the widget there instead of creating a new one. The sidebar should feel like a natural, well-organized set of tabs — not one page per widget.

### Widget sizing and layout

**Widgets must be compact and small.** Content should be top-left aligned, not centered. Prefer small, dense cards over large sprawling ones.

Default widget style — matches the app shell appearance:
```tsx
<div className="rounded-2xl bg-muted p-4">
  {/* widget content */}
</div>
```

Page components should use an auto-fit grid wrapper for their widgets. This ensures columns adjust to available width automatically:

```tsx
export function OverviewPage() {
  return (
    <div className="grid gap-4 grid-cols-[repeat(auto-fit,minmax(280px,1fr))]">
      <MetricCard />
      <MetricCard />
      <MetricCard />
      <StreakWidget />
      <TaskList />
      <QuickChart className="col-span-2" />
    </div>
  )
}
```

**Most widgets should be `col-span-1` (the default).** A page with 5 widgets should typically have 4-5 single-column widgets and at most 1 wider one. Resist the urge to make things wide — small, dense cards look better and use space more efficiently.

Guidelines for choosing span:
- **`col-span-1`** (default): metric cards, counters, status indicators, small lists, trackers — **this should be the vast majority of widgets**
- **`col-span-2`**: only for charts/graphs that genuinely need horizontal space to be readable. Not for lists, cards, or text content
- **`col-span-full`**: almost never needed. Only for wide data tables with many columns

**Do NOT wrap widgets in their own grid.** Each widget should be a single grid child — the page grid controls the layout. Never use `grid-cols-1` inside a widget or page section.

### Adding a page

1. Create `src/pages/my-page.tsx`:
```tsx
export function MyPage() {
  return (
    <div className="grid gap-4 grid-cols-[repeat(auto-fit,minmax(280px,1fr))]">
      <SmallWidget />
      <SmallWidget />
      <SmallWidget />
      <SmallWidget />
    </div>
  )
}
```

2. Add it to the **top** of the `pages` array in `config.tsx` (new pages go first):
```tsx
import { MyPage } from "./pages/my-page"
import { StarIcon } from "lucide-react"

// First entry in the pages array:
{ id: "my-page", title: "My Page", icon: <StarIcon />, component: MyPage },
```

3. Rebuild (see below)

### Example components

Read `src/examples/` for inspiration when building pages. These are reference implementations showing common patterns: individual metric cards with trends (`section-cards.tsx`), interactive area charts (`chart-area-interactive.tsx`), and grid layout with mixed widget sizes (`layout-example.tsx`). Copy and adapt individual components into your page grid — don't copy wrapper grids or layout containers from examples.

## After every change (IMPORTANT)

**Rebuild, Register with VESTAD, Restart the server and Notify the Vesta App**

```bash
cd ~/vesta/skills/dashboard/app && npx vite build
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services \
  -H 'Content-Type: application/json' -d '{"name":"dashboard"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")
screen -S dashboard -X quit 2>/dev/null
screen -dmS dashboard sh -c "cd ~/vesta/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
# Wait for the server to be ready
for i in $(seq 1 20); do curl -s -o /dev/null http://localhost:$PORT && break; sleep 0.5; done
# Smoke test: fetch the page and check for runtime errors
SMOKE=$(curl -s http://localhost:$PORT/ | head -50)
if ! echo "$SMOKE" | grep -q '<div id="root"'; then
  echo "ERROR: Dashboard failed to load. Check the build output."
fi
```

**Before notifying the app**, always verify your page renders without errors. After the server starts, open the page in a headless check or review your code for these common crash sources:
- Arrays/objects that may be `undefined` on first render (empty localStorage, no API response yet) — always default to `[]` or `{}`
- Chart components that receive `undefined` config or data
- `.reduce()`, `.map()`, `.filter()` on values that might not be arrays yet

## Data patterns

**All meaningful data must persist server-side** so it syncs across devices. Never hardcode user data (habits, bookmarks, lists, settings, etc.) in source files or rely on `localStorage` as the source of truth — the user accesses the dashboard from multiple devices and expects the same data everywhere.

Create a skill with API endpoints to store and retrieve user data, then call those endpoints from widgets using `apiFetch` from `@/lib/parent-bridge`. It handles auth and the base URL automatically and waits for the auth token before making requests, so it's safe to call on mount.

`localStorage` is only for **visual/navigation state** that is device-specific — sidebar order, collapsed sections, scroll positions, selected tabs. Prefix keys with `vesta-dashboard-` to avoid collisions.

**Never fetch external APIs directly from widget code** — the browser will block cross-origin requests (CORS). Instead, create a skill that fetches the data server-side and exposes it as an endpoint, then call that endpoint from the widget.

Widgets that fetch data **must show a loading state** while waiting — use skeletons or spinners to provide a nice ux while data loads.

### Keeping data fresh

The dashboard should always show current information. Choose the right strategy based on how often the data changes:

1. **Fetch on mount** (default) — fetch data in a `useEffect` when the widget mounts. Good for data that doesn't change frequently (daily stats, settings, lists).
2. **Fetch on mount + refresh button** — same as above but add a visible refresh button so the user can manually update. Good for data that changes throughout the day (notifications, task lists, feeds).
3. **Polling** — fetch on an interval (`setInterval` in a `useEffect`). Only use for data that changes frequently and the user expects to see live (stock prices, active timers, live metrics). Keep intervals reasonable (30s+).

Always prefer simpler strategies. Most widgets should fetch on mount with a refresh button. Polling is rarely needed.

## Removing components

1. Remove the page from `config.tsx`
2. Delete the source file(s) from `pages/`
3. Rebuild and restart (same as above)

## Syncing shared files

The dashboard reuses UI components, styles, and utilities from the main Vesta app. Run `sync-app.sh` to sync them — it uses `$VESTA_VERSION` (set by vestad) to fetch from the correct branch or release tag. It's idempotent and skips if already up to date:

```bash
~/vesta/skills/dashboard/sync-app.sh
```

## UI components

**Before every UI change**, read the full shadcn skill at [shadcn/SKILL.md](./shadcn/SKILL.md) — including the linked rule files (`styling.md`, `forms.md`, `composition.md`, `icons.md`) relevant to your change. This is not optional. The skill contains critical rules, correct patterns, and component APIs that you must follow. Re-read it every time, not just the first time.

Try to keep everything compact, dashboard space is at a premium.

**Make it fun.** Use lucide icons for visual flair in labels, headers, and status text (`<Flame />` for streaks, `<CheckCircle />` for completed, `<AlertTriangle />` for alerts, etc.). Use colorful Tailwind classes — `text-green-500`, `bg-amber-100`, `border-pink-400` — for badges, indicators, progress bars, and anything that benefits from visual pop. The dashboard should feel lively and personal, not corporate. Semantic colors for structure, raw colors for personality.

## Rules

- **No client-side fetches to external APIs** — the dashboard runs in a browser, so cross-origin requests to third-party APIs (Yahoo Finance, weather services, etc.) will be blocked by CORS. Instead, create a skill that fetches the data server-side and expose it as a skill API endpoint, then call it from the widget using `apiFetch`.
- **Use the UI components** from `@/components/ui/` — read them before building
- **State**: `useState` / `useEffect` for local state
- **localStorage**: only for device-specific visual state (sidebar order, collapsed sections, selected tabs) — never for user data
- **No hardcoded user data**: all meaningful data (habits, lists, settings, etc.) must live server-side behind skill API endpoints so it syncs across devices
- **No new dependencies**: only use packages in the dashboard's `package.json`

## Troubleshooting

- **Dashboard not showing?** `screen -ls | grep dashboard`
- **Check registration:** `curl -sk https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services`
- **Restart server:** Rebuild, get port from vestad, restart screen (same as "After every change")
