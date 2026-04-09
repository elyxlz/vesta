---
name: dashboard
description: Use when you need to build, modify, or customize anything on the user's dashboard — widgets, layouts, pages, views, or any custom UI.
serve: PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H 'Content-Type: application/json' -d '{"name":"dashboard"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])") && screen -dmS dashboard sh -c "cd ~/vesta/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
---

# Dashboard

A React app embedded in the main Vesta app. Uses a sidebar layout with page-based navigation. The agent configures pages, sidebar items, and content by editing `config.tsx` and creating page components.

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
├── examples/            ← reference components from shadcn dashboard-01 (read for inspiration)
│   ├── section-cards.tsx       ← metric cards with trend badges
│   ├── chart-area-interactive.tsx ← interactive area chart
│   ├── data-table.tsx          ← sortable data table with drag-and-drop
│   └── data.json               ← sample table data
├── components/
│   ├── ui/              ← shadcn components (synced, do NOT modify)
│   ├── app-sidebar.tsx  ← sidebar component (reads from config)
│   ├── site-header.tsx  ← header with page title
│   ├── nav-main.tsx     ← main nav items
│   ├── nav-secondary.tsx
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
  secondaryNav: [],   // optional: sidebar bottom nav items
}
```

Each `pages` entry creates a sidebar nav item. Clicking it renders that page's `component` in the content area.

### Adding a page

1. Create `src/pages/my-page.tsx`:
```tsx
export function MyPage() {
  return (
    <div className="flex flex-col gap-4 py-4 md:gap-6 md:py-6">
      <div className="px-4 lg:px-6">
        <h2 className="text-lg font-semibold">My Page</h2>
        {/* page content */}
      </div>
    </div>
  )
}
```

2. Add it to `config.tsx`:
```tsx
import { MyPage } from "./pages/my-page"
import { StarIcon } from "lucide-react"

// In the pages array:
{ id: "my-page", title: "My Page", icon: <StarIcon />, component: MyPage },
```

3. Rebuild (see below)

### Example components

Read `src/examples/` for inspiration when building pages. These are reference implementations from shadcn's dashboard-01 block showing common patterns: metric cards with trends, interactive area charts, and sortable data tables with drag-and-drop. Copy and adapt what you need into your pages.

### Empty state

When no pages are configured, set `SHOW_EMPTY_STATE = true` in `App.tsx` to show the placeholder. Set it to `false` once pages are added.

## After every change (IMPORTANT)

**Rebuild, Register with VESTAD, Restart the server and Notify the Vesta App**

```bash
cd ~/vesta/skills/dashboard/app && npx vite build
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services \
  -H 'Content-Type: application/json' -d '{"name":"dashboard"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")
screen -S dashboard -X quit 2>/dev/null
screen -dmS dashboard sh -c "cd ~/vesta/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
# Wait for the server to be ready before notifying the app
for i in $(seq 1 20); do curl -s -o /dev/null http://localhost:$PORT && break; sleep 0.5; done
curl -s -X POST "http://localhost:$WS_PORT/events/service-update?agent_token=$AGENT_TOKEN" \
  -H 'Content-Type: application/json' -d '{"service":"dashboard","action":"updated"}'
```

## Data patterns

### Static data (habits, bookmarks, etc.)

Data that the user dictates and that only changes when they ask you to update it. Two approaches depending on whether the user wants persistence:

Hardcode defaults in the source. When the user asks to permanently add/remove items, edit the file and rebuild.

If the component has interactive state the user can change (checking items, toggling things, reordering), **always persist it to `localStorage`** so changes survive reloads. Pattern:

Always prefix keys with `vesta-dashboard-` to avoid collisions.

### Dynamic data (skill APIs, third-party services, etc.)

Data that comes from somewhere else and changes dynamically — an existing skill's API, a new skill you create, or a third-party service.

**Never fetch external APIs directly from widget code** — the browser will block cross-origin requests (CORS). Instead, create a skill that fetches the data server-side and exposes it as an endpoint, then call that endpoint from the widget.

To call your skills use `apiFetch` from `@/lib/parent-bridge`. It handles auth and the base URL automatically. `apiFetch` waits for the auth token from the parent app before making requests, so it's safe to call on mount.

Widgets that fetch data **must show a loading state** while waiting — use skeletons or spinners to provide a nice ux while data loads.


## Removing components

1. Remove the page from `config.tsx`
2. Delete the source file(s) from `pages/`
3. Rebuild and restart (same as above)
4. If removing everything, set `SHOW_EMPTY_STATE = true` in `App.tsx`

## Syncing shared files

The dashboard reuses UI components, styles, and utilities from the main Vesta app. Run `sync-app.sh` to sync them — it uses `$VESTA_VERSION` (set by vestad) to fetch from the correct branch or release tag. It's idempotent and skips if already up to date:

```bash
~/vesta/skills/dashboard/sync-app.sh
```

## UI components

**Before every UI change**, read the full shadcn skill at [shadcn/SKILL.md](./shadcn/SKILL.md) — including the linked rule files (`styling.md`, `forms.md`, `composition.md`, `icons.md`) relevant to your change. This is not optional. The skill contains critical rules, correct patterns, and component APIs that you must follow. Re-read it every time, not just the first time.

Try to keep everything compact, dashboard space is at a premium.

## Rules

- **No client-side fetches to external APIs** — the dashboard runs in a browser, so cross-origin requests to third-party APIs (Yahoo Finance, weather services, etc.) will be blocked by CORS. Instead, create a skill that fetches the data server-side and expose it as a skill API endpoint, then call it from the widget using `apiFetch`.
- **Use the UI components** from `@/components/ui/` — read them before building
- **State**: `useState` / `useEffect` for local state
- **localStorage**: use it for persisting UI state (checked items, preferences), not as a primary data store. Always have hardcoded defaults as fallback
- **No new dependencies**: only use packages in the dashboard's `package.json`

## Troubleshooting

- **Dashboard not showing?** `screen -ls | grep dashboard`
- **Check registration:** `curl -sk https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services`
- **Restart server:** Rebuild, get port from vestad, restart screen (same as "After every change")
