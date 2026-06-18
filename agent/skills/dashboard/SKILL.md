---
name: dashboard
description: Build or modify the user's dashboard: widgets, pages, layouts, or custom UI.
serve: PORT=$(~/agent/skills/service/scripts/register-service dashboard --public) && screen -dmS dashboard sh -c "cd ~/agent/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
---

# Dashboard

A React app embedded in the main Vesta app that serves as the user's **life HQ**, a personal command center for health, finances, productivity, habits, goals, and anything else they want to track and manage. Uses a sidebar layout with page-based navigation. The agent configures pages, sidebar items, and content by editing `config.tsx` and creating page components.

## Before building

Ask the user three things before writing code, then build only after they've answered:

1. **Goal**: if the request is vague, clarify what they actually want to see or do
2. **Interaction**: display-only, or do they want to tap/click/toggle/input things?
3. **Data**: should it show fixed sample data, or pull in live data from a skill or API? Does the info need to stay in sync and look the same across different Vesta apps (like mobile)?

**Exception, dreamer auto-builds.** During a dream pass, the agent may add widgets without asking. See the `dream` skill for when and how.

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

## Density & Sizing Rules

The dashboard is a high-density UI, not a standard app interface. Default shadcn components are too large for it: override them so everything feels compact. Large elements are the exception.

**1. Typography**
*   Default text: `text-sm`
*   Secondary text / labels: `text-xs text-muted-foreground`. Do NOT lower the opacity (no `text-muted-foreground/70`), especially on tiny labels like `text-[10px]`: it washes out and becomes unreadable on the dark theme.
*   Large numbers only: `text-lg` or `text-xl font-semibold`
*   Reserve `text-lg`+ for genuinely large numbers or when the user asks for it.

**2. Padding, Spacing & Layout**
*   Default widget wrapper: `<div className="rounded-2xl bg-secondary p-3 text-sm">`
*   Dense widgets: `p-2`. Reserve `p-4` for the rare case it actually needs the room.
*   Grid gap: Use `gap-2` (preferred) or `gap-3`. Reserve `gap-4`.
*   Inside widgets: Use `space-y-2` instead of `space-y-4`.
*   Prefer horizontal density over tall widgets. Combine related info into single rows.

**3. Buttons & Controls**
*   Compact buttons by default: `<Button size="sm" className="h-8 px-2 text-xs">`
*   Inputs: `h-8 text-xs`. Reserve full-width inputs for cases that genuinely need them.
*   Reserve the default `<Button>` size for when the user asks for it.

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

## Data Patterns

**1. No client-side external API fetches.** The dashboard runs in a browser; cross-origin requests to third-party APIs (weather, finance) fail due to CORS. Create a skill that fetches data server-side, expose it as an endpoint, and call it from the dashboard using `apiFetch` from `@/lib/parent-bridge`.

**2. Persist user data server-side.** The user reads the dashboard across devices, so the source of truth lives in a skill with API endpoints. Hardcoded data and `localStorage` shouldn't act as the canonical store.

**3. `localStorage` is for local visual state only.** Use it for device-specific UI states (sidebar order, collapsed sections, selected tabs). Prefix keys with `vesta-dashboard-`.

**4. Loading and missing data:**
*   Show a skeleton or spinner while data is loading.
*   Arrays/objects may be undefined on first render. Default to `[]` or `{}` so `.reduce()`, `.map()`, and charts don't crash.

**5. Data freshness:** Default to fetching on mount (`useEffect`). For data that updates through the day, add a compact refresh button. Reserve polling (`setInterval`) for live data like timers or stock tickers, and ask the user how often it should auto-refresh.

## UI & Styling

*   **Read the docs:** Before every UI change, read `shadcn/SKILL.md` and its linked rules.
*   **Make it fun:** Use lucide icons for visual flair (like `<Flame />` for streaks, `<CheckCircle />` for completed).
*   **Use semantic colors:** Use Tailwind classes (like `text-green-500`, `bg-amber-100`, `border-pink-400`) for badges, progress bars, and status indicators.

## After every change

Rebuild, re-register with vestad, restart the preview server, and notify the Vesta app:

```bash
# First build only: node_modules is not baked into the image, so install deps once.
cd ~/agent/skills/dashboard/app && { [ -d node_modules ] || npm install; } && npx vite build
PORT=$(~/agent/skills/service/scripts/register-service dashboard --public)
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

## Cache gotchas (read once)

- **Do NOT pass `--base`** to vite preview. Vestad strips the `/agents/{name}/{service}/` prefix when proxying, so the local server must serve at `/`. With `--base` set, `/assets/...` requests come in stripped and 404. The HTML uses relative `./assets/...` already (vite config `base: "./"`), which resolves correctly under the proxy path in the browser.
- **Cloudflare caches 404 responses for ~4 hours via the public tunnel.** If you accidentally serve a broken build that 404s on assets, even after fixing the build, the tunnel will keep serving the cached 404 until either (a) the URL changes, (b) the cache expires, or (c) you bust with a `?v=...` query. Vite's content hashes change automatically when source changes, so normally this isn't an issue. If you ever get a stuck 404 with no source change, temporarily add `Date.now()` to `entryFileNames` in `vite.config.ts`, rebuild, then revert.

## Troubleshooting
*   **Dashboard not showing?** `screen -ls | grep dashboard`
*   **Check registration:** `curl -sk https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services`
*   **Restart server:** Run the rebuild/restart block above.
*   **Build failed or blank after deploy?** Run `cd ~/agent/skills/dashboard/app && { [ -d node_modules ] || npm install; } && npx vite build` and fix reported errors; confirm `app/dist/` exists before starting preview. `UNRESOLVED_IMPORT` / "Cannot find package" means deps were never installed, run `npm install` first.
*   **Iframe stuck on an old build?** After a successful build and preview restart, run the `.../services/dashboard/invalidate` `curl` from the block above (the parent app keeps the iframe until invalidated).
*   **Preview errors or 404?** Attach to logs with `screen -r dashboard`, then detach with Ctrl+A then `d`. If the session is wedged, `screen -S dashboard -X quit` and rerun the restart line from the block above.
*   **No port from vestad?** Run the `POST .../services` `curl` alone and inspect the body; the `python3` one-liner errors on bad JSON. Verify `VESTAD_PORT`, `AGENT_NAME`, and `AGENT_TOKEN`.
*   **Widgets or API calls failing?** Use devtools on the dashboard (network tab): wrong `apiFetch` paths, skill server down, or auth not ready yet (`waitForAuth` in `parent-bridge.ts`).
*   **Wrong or missing shadcn styles?** Shared UI components are updated via upstream sync. Check that the latest release tag has been merged.
