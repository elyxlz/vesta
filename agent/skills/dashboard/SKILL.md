---
name: dashboard
description: Build or modify the user's dashboard: widgets, pages, layouts, or custom UI.
serve: PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' -d '{"name":"dashboard","public":true}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])") && screen -dmS dashboard sh -c "cd ~/agent/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
---

# Dashboard

A React app embedded in the main Vesta app that serves as the user's **life HQ**, a personal command center for health, finances, productivity, habits, goals, and anything else they want to track and manage. Uses a sidebar layout with page-based navigation. The agent configures pages, sidebar items, and content by editing `config.tsx` and creating page components.

## Before building (REQUIRED)

**1. Ask clarifying questions:** You MUST ask the user before writing any code. Go through these:
1. **Goal**: if the request is vague, clarify what they actually want to see or do
2. **Interaction**: display-only, or do they want to tap/click/toggle/input things?
3. **Data**: should it show fixed sample data, or pull in live data from a skill or API? Does the info need to stay in sync and look the same across different Vesta apps (like mobile)?

Only start building once the user has answered. Don't assume. Ask.

## Project structure

```text
~/agent/skills/dashboard/app/src/
├── App.tsx              ← layout shell (sidebar + content area)
├── config.tsx           ← EDIT THIS: define pages, sidebar nav, branding
├── main.tsx             ← do NOT modify
├── index.css            ← do NOT modify (synced from main app)
├── pages/               ← page components (one per sidebar nav item)
├── examples/            ← reference components (read for inspiration, BUT scale down their sizes)
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

**You can freely edit:** `config.tsx`, `App.tsx`, anything in `pages/`, `components/`, `widgets/`, and any new files you create.
**Do NOT modify:** `main.tsx`, `index.css`, `lib/utils.ts`, `hooks/`, `components/ui/`

## How it works

The dashboard uses a **sidebar + page** layout controlled by `config.tsx`. Each `pages` entry creates a sidebar nav item. Clicking it renders that page's component. Pages can have `children` to create collapsible sub-pages in the sidebar.

When adding a widget without a specified page, **choose a fitting page name yourself**. Group related widgets under a meaningful category (e.g., "Health" with `<HeartIcon />`, "Finance" with `<DollarSignIcon />`). If a suitable page already exists, add the widget there.

## Density & Sizing Rules (IMPORTANT)

The dashboard is a high-density UI, not a standard app interface. By default, shadcn components are too large. **You MUST override them**. Everything should feel compact. Large elements are the exception, not the norm.

**1. Typography (MANDATORY)**
*   Default text: `text-sm`
*   Secondary text / labels: `text-xs text-muted-foreground`
*   Large numbers only: `text-lg` or `text-xl font-semibold`
*   Do not use `text-lg` or larger for normal text unless absolutely necessary or the user explicitly requests it.

**2. Padding, Spacing & Layout (MANDATORY)**
*   Default widget wrapper: `<div className="rounded-2xl bg-secondary p-3 text-sm">`
*   Dense widgets: `p-2`. Avoid `p-4` unless absolutely necessary.
*   Grid gap: Use `gap-2` (preferred) or `gap-3`. Avoid `gap-4`.
*   Inside widgets: Use `space-y-2` instead of `space-y-4`.
*   Avoid tall widgets. Prefer horizontal density. Combine related info into single rows.

**3. Buttons & Controls (MANDATORY)**
*   All buttons must be compact: `<Button size="sm" className="h-8 px-2 text-xs">`
*   Inputs: `h-8 text-xs`. Avoid full-width inputs unless necessary.
*   Do not use the default `<Button>` size unless absolutely necessary or the user explicitly requests it.

**4. Grid Span Rules**
*   **col-span-1** (default): metric cards, counters, status indicators, trackers. *This is 90% of widgets.*
*   **col-span-2**: Only for charts/graphs that genuinely need horizontal space.
*   **col-span-full**: Almost never needed (only wide data tables).

### Adding a page

1. Create `src/pages/my-page.tsx` with whatever layout fits the content (single column, tables, etc.).

**Example (grid layout page)** for a widget-heavy page: a responsive auto-fill grid with compact gaps.

```tsx
export function MyPage() {
  return (
    <div className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(280px,1fr))]">
      <SmallWidget />
      <SmallWidget />
    </div>
  )
}
```

2. Add it to the **top** of the `pages` array in `config.tsx`:
```tsx
import { MyPage } from "./pages/my-page"
import { StarIcon } from "lucide-react"

// Inside config.pages:
{ id: "my-page", title: "My Page", icon: <StarIcon />, component: MyPage },
```

## Data Patterns & Strict Rules

**1. No client-side external API fetches:** The dashboard runs in a browser; cross-origin requests to third-party APIs (weather, finance) will fail due to CORS. You MUST create a skill that fetches data server-side, expose it as an endpoint, and call it using `apiFetch` from `@/lib/parent-bridge`.

**2. All user data must persist server-side:** Do not hardcode user data or rely on `localStorage` as the source of truth. The user accesses the dashboard across devices. Create a skill with API endpoints to store/retrieve data.

**3. `localStorage` is ONLY for local visual state:** Use it strictly for device-specific UI states (sidebar order, collapsed sections, selected tabs). Prefix keys with `vesta-dashboard-`.

**4. Handle loading and missing data:**
*   Widgets fetching data **must** show a skeleton or spinner while loading.
*   Prevent crashes: Arrays/objects may be undefined on first render. Always default to `[]` or `{}`. Protect `.reduce()`, `.map()`, and charts from undefined data.

**5. Data freshness:** Default to fetching on mount (`useEffect`). For data that updates throughout the day, add a compact refresh button. Only use polling (`setInterval`) for live data like timers or stock tickers (ask the user how often it should auto refresh).

## UI & Styling

*   **Read the docs:** Before every UI change, read `shadcn/SKILL.md` and its linked rules.
*   **Make it fun:** Use lucide icons for visual flair (like `<Flame />` for streaks, `<CheckCircle />` for completed).
*   **Use semantic colors:** Use Tailwind classes (like `text-green-500`, `bg-amber-100`, `border-pink-400`) for badges, progress bars, and status indicators.

## After every change (IMPORTANT)

**Rebuild, Register with VESTAD, Restart the server and Notify the Vesta App**

```bash
cd ~/agent/skills/dashboard/app && npx vite build
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services \
  -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' -d '{"name":"dashboard","public":true}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")
screen -S dashboard -X quit 2>/dev/null
screen -dmS dashboard sh -c "cd ~/agent/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
# Wait for the server to be ready
for i in $(seq 1 20); do curl -s -o /dev/null http://localhost:$PORT && break; sleep 0.5; done
# Smoke test: fetch the page and check for runtime errors
SMOKE=$(curl -s http://localhost:$PORT/ | head -50)
if ! echo "$SMOKE" | grep -q '<div id="root"'; then
  echo "ERROR: Dashboard failed to load. Check the build output."
fi
# Notify the app to reload the dashboard iframe
curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services/dashboard/invalidate -H "X-Agent-Token: $AGENT_TOKEN"
```

## Troubleshooting
*   **Dashboard not showing?** `screen -ls | grep dashboard`
*   **Check registration:** `curl -sk https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services`
*   **Restart server:** Run the rebuild/restart block above.
*   **Build failed or blank after deploy?** Run `cd ~/agent/skills/dashboard/app && npx vite build` and fix reported errors; confirm `app/dist/` exists before starting preview.
*   **Iframe stuck on an old build?** After a successful build and preview restart, run the `.../services/dashboard/invalidate` `curl` from the block above (the parent app keeps the iframe until invalidated).
*   **Preview errors or 404?** Attach to logs with `screen -r dashboard`, then detach with Ctrl+A then `d`. If the session is wedged, `screen -S dashboard -X quit` and rerun the restart line from the block above.
*   **No port from vestad?** Run the `POST .../services` `curl` alone and inspect the body; the `python3` one-liner errors on bad JSON. Verify `VESTAD_PORT`, `AGENT_NAME`, and `AGENT_TOKEN`.
*   **Widgets or API calls failing?** Use devtools on the dashboard (network tab): wrong `apiFetch` paths, skill server down, or auth not ready yet (`waitForAuth` in `parent-bridge.ts`).
*   **Wrong or missing shadcn styles?** Shared UI components are updated via upstream sync. Check that the latest release tag has been merged.
